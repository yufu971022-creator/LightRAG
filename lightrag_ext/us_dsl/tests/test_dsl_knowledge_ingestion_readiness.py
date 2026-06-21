from __future__ import annotations

import json
from pathlib import Path
import subprocess

from lightrag_ext.us_dsl.dsl_knowledge_ingestion_policy import (
    prepare_policy_approved_ingestion_payload,
)
from lightrag_ext.us_dsl.dsl_knowledge_ingestion_readiness import (
    run_ingestion_readiness_gate,
)
from lightrag_ext.us_dsl.dsl_knowledge_ingestion_types import (
    DslKnowledgeIngestionConfig,
    serialize_dsl_knowledge_ingestion_report,
)
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship


def test_readiness_disabled_skips():
    report = run_ingestion_readiness_gate(
        config=DslKnowledgeIngestionConfig(
            enabled=False,
            namespace="dsl_test_readiness_disabled",
            module_name="LCAB",
        )
    )

    assert report.skipped is True
    assert report.ready_to_write is False
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_succeeded is False


def test_readiness_gate_builds_payload():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.ready_to_write is True
    assert report.source_us_count > 0
    assert report.source_text_unit_count > 0
    assert report.kg_payload_entity_count > 0
    assert report.kg_payload_relationship_count > 0


def test_readiness_gate_version_policy_ready():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.version_policy_ready is True
    assert report.unsafe_supersedes_blocked_count == 0
    assert report.source_order_supersedes_count == 0
    assert report.version_review_required_after <= report.version_review_required_before


def test_readiness_gate_blocks_unsafe_objects():
    report = run_ingestion_readiness_gate(
        dsl_payload=_unsafe_payload(),
        config=DslKnowledgeIngestionConfig(
            enabled=True,
            namespace="dsl_test_readiness_unsafe",
            module_name="TEST",
        ),
    )

    assert report.ready_to_write is True
    assert report.custom_kg_entity_count == 1
    assert report.custom_kg_relationship_count == 0
    assert report.review_required_blocked_count > 0
    assert report.info_only_blocked_count > 0
    assert report.version_review_required_blocked_count > 0
    assert report.evidence_missing_count > 0
    assert report.invalid_relation_blocked_count > 0
    assert report.forbidden_relation_blocked_count > 0


def test_readiness_gate_custom_kg_has_no_unsafe_objects():
    prepared = prepare_policy_approved_ingestion_payload(
        _unsafe_payload(),
        namespace="dsl_test_readiness_no_unsafe_custom_kg",
    )
    text = json.dumps(prepared.custom_kg_input)

    assert "ReviewRequired" not in text
    assert "InfoOnly" not in text
    assert "VersionReviewRequired" not in text
    assert "MissingEvidence" not in text
    assert "InvalidRelation" not in text


def test_readiness_gate_no_forbidden_relations():
    prepared = prepare_policy_approved_ingestion_payload(
        _unsafe_payload(),
        namespace="dsl_test_readiness_no_forbidden",
    )
    forbidden = {
        "has_child",
        "belongs_to",
        "references_to",
        "queries_from",
        "queries_by",
        "contains",
    }

    assert not [
        item
        for item in prepared.custom_kg_input["relationships"]
        if str(item.get("keywords")).lower() in forbidden
    ]
    assert prepared.forbidden_relation_count == 0


def test_readiness_gate_sidecar_alignment():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.sidecar_alignment_passed is True
    assert report.sidecar_record_count == (
        report.custom_kg_chunk_count
        + report.custom_kg_entity_count
        + report.custom_kg_relationship_count
    )


def test_readiness_gate_endpoint_closure():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.endpoint_closure_passed is True
    assert report.dangling_relationship_count == 0
    assert report.forbidden_relation_count == 0


def test_readiness_gate_idempotency_keys_unique():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.idempotency_key_duplicate_count == 0
    assert report.idempotency_passed is True


def test_readiness_gate_rollback_plan_present():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.ready_to_write is True
    assert report.rollback_plan_present is True
    assert report.rollback_key_count >= (
        report.custom_kg_entity_count + report.custom_kg_relationship_count
    )
    assert report.rollback_strategy == "delete_by_id"


def test_readiness_gate_blocked_count_semantics():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.blocked_count == report.blocked_object_count
    assert report.blocked_reason_occurrence_count == sum(
        report.block_reason_distribution.values()
    )
    assert report.blocked_object_count <= (
        report.kg_payload_entity_count + report.kg_payload_relationship_count
    )
    assert report.blocked_reason_occurrence_count >= report.blocked_object_count


def test_readiness_gate_batch_plan():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.batch_count > 0


def test_readiness_gate_ready_to_write():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.ready_to_write is True
    assert report.recommended_next_step == "RUN_CANARY_TEST_GRAPH_INGESTION"


def test_readiness_gate_not_call_graph_write():
    report = run_ingestion_readiness_gate(config=_lc_config())

    assert report.stage == "readiness"
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_succeeded is False
    assert report.neo4j_connected is False
    assert report.production_write is False


def test_readiness_gate_no_graph_write():
    test_readiness_gate_not_call_graph_write()


def test_idempotency_keys_stable():
    payload = _valid_payload()
    first = prepare_policy_approved_ingestion_payload(
        payload,
        namespace="dsl_test_idempotency",
    )
    second = prepare_policy_approved_ingestion_payload(
        payload,
        namespace="dsl_test_idempotency",
    )

    assert first.idempotency_keys == second.idempotency_keys
    assert first.idempotency_key_duplicate_count == 0


def test_readiness_report_serializable():
    report = run_ingestion_readiness_gate(config=_lc_config())

    json.dumps(serialize_dsl_knowledge_ingestion_report(report))


def test_no_lightrag_core_modified():
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "lightrag"],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.stdout.strip() == ""


def _lc_config() -> DslKnowledgeIngestionConfig:
    return DslKnowledgeIngestionConfig(
        enabled=True,
        namespace="dsl_test_readiness",
        module_name="LCAB",
        max_chunks=20,
        max_entities=50,
        max_relationships=50,
    )


def _valid_payload() -> DslKgPayload:
    metadata = _metadata()
    return DslKgPayload(
        chunks=[
            KgChunk(
                content="Test feature has field Alpha.",
                source_id="tu-1",
                metadata={**metadata, "validationStatus": "CHUNK", "reviewDecision": "CHUNK"},
            )
        ],
        entities=[
            KgEntity(
                entity_name="Test Feature",
                entity_type="FeatureCatalog",
                description="Test feature.",
                source_id="tu-1",
                metadata={**metadata, "candidateId": "entity-feature"},
            ),
            KgEntity(
                entity_name="Alpha",
                entity_type="FieldSpec",
                description="Alpha is a field.",
                source_id="tu-1",
                metadata={**metadata, "candidateId": "entity-alpha"},
            ),
        ],
        relationships=[
            KgRelationship(
                src_id="Test Feature",
                tgt_id="Alpha",
                description="Test feature has field Alpha.",
                keywords="HasFieldSpec",
                source_id="tu-1",
                metadata={**metadata, "candidateId": "relation-alpha", "relationType": "HasFieldSpec"},
            )
        ],
        metadata={"moduleName": "TEST", "source": "test-source"},
    )


def _unsafe_payload() -> DslKgPayload:
    metadata = _metadata()
    return DslKgPayload(
        chunks=[
            KgChunk(
                content="Unsafe test source.",
                source_id="tu-unsafe",
                metadata={**metadata, "validationStatus": "CHUNK", "reviewDecision": "CHUNK"},
            )
        ],
        entities=[
            KgEntity(
                entity_name="Unsafe Feature",
                entity_type="FeatureCatalog",
                description="Unsafe feature.",
                source_id="tu-unsafe",
                metadata={**metadata, "candidateId": "entity-safe"},
            ),
            KgEntity(
                entity_name="Needs Review Field",
                entity_type="FieldSpec",
                description="ReviewRequired field.",
                source_id="tu-unsafe",
                metadata={
                    **metadata,
                    "candidateId": "entity-review",
                    "reviewDecision": "REVIEW_REQUIRED",
                    "knowledgeStatus": "ReviewRequired",
                },
            ),
            KgEntity(
                entity_name="Info Field",
                entity_type="FieldSpec",
                description="InfoOnly field.",
                source_id="tu-unsafe",
                metadata={
                    **metadata,
                    "candidateId": "entity-info",
                    "reviewDecision": "INFO_ONLY",
                    "knowledgeStatus": "InfoOnly",
                },
            ),
            KgEntity(
                entity_name="Missing Evidence Field",
                entity_type="FieldSpec",
                description="Missing evidence field.",
                source_id="tu-unsafe",
                metadata={
                    **metadata,
                    "candidateId": "entity-missing",
                    "evidenceText": None,
                    "validationStatus": "MISSING_EVIDENCE",
                },
            ),
        ],
        relationships=[
            KgRelationship(
                src_id="Unsafe Feature",
                tgt_id="Needs Review Field",
                description="VersionReviewRequired relation.",
                keywords="HasVersion",
                source_id="tu-unsafe",
                metadata={
                    **metadata,
                    "candidateId": "relation-version-review",
                    "relationType": "HasVersion",
                    "reasonCode": "VersionReviewRequired",
                    "requiresHumanReview": True,
                },
            ),
            KgRelationship(
                src_id="Unsafe Feature",
                tgt_id="Info Field",
                description="Forbidden relation.",
                keywords="has_child",
                source_id="tu-unsafe",
                metadata={
                    **metadata,
                    "candidateId": "relation-forbidden",
                    "relationType": "has_child",
                    "validationStatus": "InvalidRelation",
                },
            ),
        ],
        metadata={"moduleName": "TEST", "source": "unsafe-source"},
    )


def _metadata() -> dict:
    return {
        "documentId": "TEST-DOC",
        "sourceUsId": "US-TEST-001",
        "textUnitId": "tu-1",
        "sourceSpan": {"start": 0, "end": 20},
        "textHash": "hash-test",
        "evidenceText": "Test feature has field Alpha.",
        "featureKey": "TestFeature",
        "domainCode": "MasterData",
        "sectionType": "field_table",
        "knowledgeStatus": "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": "AUTO_ACCEPT_FOR_REPORT",
        "confidenceScore": 1.0,
        "ruleVersion": "v1",
        "latestFlag": True,
        "versionStatus": "Current",
        "supersedes": [],
    }
