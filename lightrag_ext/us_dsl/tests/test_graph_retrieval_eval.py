from __future__ import annotations

import json

from lightrag_ext.us_dsl.fx_mini_graph_smoke import (
    FX_MINI_NAMESPACE,
    build_fx_mini_kg_payload,
)
from lightrag_ext.us_dsl.graph_retrieval_eval import (
    build_lc_mini_graph_retrieval_evaluation_report,
    build_retrieval_queries_from_graph_payload,
    compare_retrieval_results,
    get_retrieval_eval_runtime_flags,
    run_graph_aware_retrieval,
    run_text_only_retrieval,
    serialize_graph_retrieval_evaluation_report,
)
from lightrag_ext.us_dsl.graph_retrieval_index import (
    build_graph_retrieval_indexes,
)
from lightrag_ext.us_dsl.graph_retrieval_types import (
    HIT_EDGE,
    HIT_NODE,
    HIT_PATH,
    IMPROVED,
    GraphRetrievalQuery,
)
from lightrag_ext.us_dsl.kg_metadata_sidecar import build_graph_insert_sidecar_records
from lightrag_ext.us_dsl.kg_payload_types import (
    DslKgPayload,
    KgChunk,
    KgEntity,
    KgRelationship,
)
from lightrag_ext.us_dsl.kg_test_graph_write import to_lightrag_custom_kg_input
from lightrag_ext.us_dsl.lc_mini_graph_smoke import (
    LC_MINI_NAMESPACE,
    build_lc_mini_kg_payload,
)


def test_build_retrieval_index_from_fx_payload():
    payload = build_fx_mini_kg_payload()
    indexes = _indexes(payload, FX_MINI_NAMESPACE)

    assert len(indexes.node_index.records) > 0
    assert len(indexes.edge_index.records) > 0
    assert len(indexes.text_index.records) > 0


def test_build_retrieval_index_from_lc_mini_payload():
    payload = build_lc_mini_kg_payload()
    sidecar = _sidecar(payload, LC_MINI_NAMESPACE)
    indexes = build_graph_retrieval_indexes(payload, sidecar)

    assert len(indexes.node_index.records) > 0
    assert len(indexes.edge_index.records) > 0
    assert len(sidecar) == len(payload.chunks) + len(payload.entities) + len(payload.relationships)


def test_query_generation_only_uses_existing_payload_objects():
    payload = build_lc_mini_kg_payload()
    sidecar = _sidecar(payload, LC_MINI_NAMESPACE)
    queries = build_retrieval_queries_from_graph_payload(payload, sidecar, max_queries=8)
    entity_names = {entity.entity_name for entity in payload.entities}
    relation_types = {relationship.keywords for relationship in payload.relationships}

    assert queries
    assert all(set(query.expected_entities) <= entity_names for query in queries)
    assert all(set(query.expected_relations) <= relation_types for query in queries)
    assert all("Nonexistent" not in query.query_text for query in queries)


def test_text_only_retrieval_returns_evidence():
    payload = build_lc_mini_kg_payload()
    sidecar = _sidecar(payload, LC_MINI_NAMESPACE)
    indexes = build_graph_retrieval_indexes(payload, sidecar)
    query = build_retrieval_queries_from_graph_payload(payload, sidecar, max_queries=1)[0]

    result = run_text_only_retrieval(query, indexes.text_index)

    assert result.hits
    assert all(hit.evidence_text for hit in result.hits)
    assert all(hit.text_hash for hit in result.hits)


def test_graph_aware_retrieval_returns_nodes_edges_paths():
    payload = build_lc_mini_kg_payload()
    sidecar = _sidecar(payload, LC_MINI_NAMESPACE)
    indexes = build_graph_retrieval_indexes(payload, sidecar)
    query = build_retrieval_queries_from_graph_payload(payload, sidecar, max_queries=1)[0]

    result = run_graph_aware_retrieval(
        query,
        indexes.text_index,
        indexes.node_index,
        indexes.edge_index,
        indexes.path_index,
    )
    graph_hits = [hit for hit in result.hits if hit.hit_type != "text"]

    assert {HIT_NODE, HIT_EDGE, HIT_PATH}.issubset({hit.hit_type for hit in graph_hits})
    assert all(hit.evidence_text and hit.text_hash for hit in graph_hits)


def test_graph_aware_improves_relation_recall_on_synthetic_case():
    payload = _synthetic_payload()
    sidecar = _sidecar(payload, "dsl_test_graph_retrieval_synthetic")
    indexes = build_graph_retrieval_indexes(payload, sidecar)
    query = GraphRetrievalQuery(
        query_id="synthetic-assigns-handler",
        query_text="Alpha 和 Beta 的待办处理关系是什么？",
        expected_domains=["Workflow"],
        expected_sections=["task_rule"],
        expected_entities=["Alpha", "Beta"],
        expected_relations=["AssignsHandler"],
        expected_evidence_keywords=["Alpha", "Beta"],
        level="L1",
    )

    text_result = run_text_only_retrieval(query, indexes.text_index)
    graph_result = run_graph_aware_retrieval(
        query,
        indexes.text_index,
        indexes.node_index,
        indexes.edge_index,
        indexes.path_index,
    )
    comparison = compare_retrieval_results(query, text_result, graph_result)

    assert text_result.expected_relation_recall == 0
    assert graph_result.expected_relation_recall == 1
    assert graph_result.graph_path_count > 0
    assert comparison.improvement_label == IMPROVED


def test_graph_aware_does_not_return_unrelated_domain():
    payload = build_lc_mini_kg_payload()
    sidecar = _sidecar(payload, LC_MINI_NAMESPACE)
    indexes = build_graph_retrieval_indexes(payload, sidecar)
    query = GraphRetrievalQuery(
        query_id="workflow-only",
        query_text="Current Handler 的待办规则证据是什么？",
        expected_domains=["Workflow"],
        expected_sections=["task_rule"],
        expected_entities=["Current Handler", "Bank Default Confirmation"],
        expected_relations=["AssignsHandler"],
        expected_evidence_keywords=["Current Handler"],
        level="L1",
    )

    result = run_graph_aware_retrieval(
        query,
        indexes.text_index,
        indexes.node_index,
        indexes.edge_index,
        indexes.path_index,
    )

    assert result.hits
    assert all(hit.domain_code in {None, "Workflow"} for hit in result.hits)
    assert not any(issue["code"] == "POTENTIAL_FALSE_POSITIVE_DOMAIN" for issue in result.issues)


def test_no_llm_called():
    payload = build_lc_mini_kg_payload()
    sidecar = _sidecar(payload, LC_MINI_NAMESPACE)
    indexes = build_graph_retrieval_indexes(payload, sidecar)
    query = build_retrieval_queries_from_graph_payload(payload, sidecar, max_queries=1)[0]

    run_graph_aware_retrieval(
        query,
        indexes.text_index,
        indexes.node_index,
        indexes.edge_index,
        indexes.path_index,
    )

    assert get_retrieval_eval_runtime_flags()["llm_called"] is False


def test_no_storage_written():
    report = build_lc_mini_graph_retrieval_evaluation_report(max_queries=3)

    assert report.query_count > 0
    assert get_retrieval_eval_runtime_flags()["storage_written"] is False
    assert get_retrieval_eval_runtime_flags()["neo4j_connected"] is False


def test_report_serializable():
    report = build_lc_mini_graph_retrieval_evaluation_report(max_queries=3)

    json.dumps(serialize_graph_retrieval_evaluation_report(report))


def test_lc_mini_graph_retrieval_report():
    report = build_lc_mini_graph_retrieval_evaluation_report(max_queries=8)

    assert report.query_count > 0
    assert report.recommended_next_step
    assert report.degraded_count == 0
    assert report.improved_count >= 1


def _indexes(payload: DslKgPayload, namespace: str):
    return build_graph_retrieval_indexes(payload, _sidecar(payload, namespace))


def _sidecar(payload: DslKgPayload, namespace: str):
    custom_kg = to_lightrag_custom_kg_input(payload)
    return build_graph_insert_sidecar_records(payload, custom_kg, namespace=namespace)


def _synthetic_payload() -> DslKgPayload:
    metadata = {
        "documentId": "DOC_SYN_001",
        "sourceUsId": "US-SYN-001",
        "textUnitId": "TU_SYN_001",
        "sourceSpan": {"start": 0, "end": 72},
        "textHash": "hash-syn-001",
        "evidenceText": "Alpha workflow evidence mentions Alpha and Beta.",
        "featureKey": "Workflow:SYN:AlphaTask",
        "domainCode": "Workflow",
        "sectionType": "task_rule",
        "knowledgeStatus": "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": "AUTO_ACCEPT_FOR_REPORT",
        "confidenceScore": 0.95,
    }
    return DslKgPayload(
        chunks=[
            KgChunk(
                content="Alpha workflow evidence mentions Alpha and Beta.",
                source_id="TU_SYN_001",
                file_path="synthetic.md",
                metadata=metadata,
            )
        ],
        entities=[
            KgEntity(
                entity_name="Alpha",
                entity_type="TaskRule",
                description="Alpha task rule.",
                source_id="TU_SYN_001",
                metadata={**metadata, "candidateId": "ent-alpha"},
            ),
            KgEntity(
                entity_name="Beta",
                entity_type="RolePermission",
                description="Beta handler.",
                source_id="TU_SYN_001",
                metadata={**metadata, "candidateId": "ent-beta"},
            ),
        ],
        relationships=[
            KgRelationship(
                src_id="Alpha",
                tgt_id="Beta",
                description="Alpha assigns handler Beta.",
                keywords="AssignsHandler",
                source_id="TU_SYN_001",
                weight=1.0,
                metadata={
                    **metadata,
                    "candidateId": "rel-alpha-beta",
                    "relationType": "AssignsHandler",
                    "evidenceText": "Alpha workflow evidence mentions Alpha and Beta.",
                },
            )
        ],
        metadata={"source": "synthetic"},
    )
