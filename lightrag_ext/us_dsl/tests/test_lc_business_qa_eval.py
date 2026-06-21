from __future__ import annotations

import json
import os

from lightrag_ext.us_dsl.graph_answer_types import AnswerGenerationResult
from lightrag_ext.us_dsl.graph_retrieval_types import INCONCLUSIVE, MODE_GRAPH_AWARE
from lightrag_ext.us_dsl.lc_business_qa_cases import (
    LCBusinessQaCase,
    default_lc_business_qa_cases,
)
from lightrag_ext.us_dsl.lc_business_qa_eval import (
    EXPANDED_LC_SUBSET_LIMITS,
    MODE_LIVE,
    MODE_OFFLINE,
    get_lc_business_qa_runtime_flags,
    run_lc_business_qa_ab_eval,
    serialize_lc_business_qa_ab_eval_report,
)
from lightrag_ext.us_dsl.lc_business_qa_judge import (
    FAIL,
    judge_lc_business_answer,
)
from lightrag_ext.us_dsl.lc_graph_subset_builder import (
    build_lc_expanded_graph_subset_from_case_pack,
)
from lightrag_ext.us_dsl.lc_mini_graph_smoke import (
    ENABLE_LC_SUBSET_SMOKE_ENV,
    LcMiniGraphSmokeConfig,
    build_lc_mini_kg_payload,
    run_lc_subset_graph_smoke,
)


def test_lc_business_cases_defined():
    cases = default_lc_business_qa_cases()

    assert len(cases) >= 8
    for case in cases:
        assert case.expected_answer_points
        assert (
            case.expected_entities
            or case.expected_domains
            or case.expected_graph_coverage == "partial"
        )


def test_lc_business_cases_do_not_depend_on_agent_output():
    cases = default_lc_business_qa_cases()

    assert all("evidence_id" not in " ".join(case.expected_answer_points) for case in cases)
    assert all("graph-aware answer" not in case.grading_notes.lower() for case in cases)


def test_run_lc_business_qa_ab_eval_offline():
    report = run_lc_business_qa_ab_eval(mode=MODE_OFFLINE, max_cases=10)

    assert report.case_count > 0
    assert report.avg_graph_score >= report.avg_text_score
    assert report.degraded_count == 0


def test_lc_graph_coverage_report_before_eval():
    cases = default_lc_business_qa_cases()
    subset_result = _expanded_subset_result(cases)
    report = subset_result.coverage_report

    assert report.case_count == 10
    assert report.full_coverage_count + report.partial_coverage_count >= 7
    assert report.no_coverage_count <= 2
    assert "LC-QA-009-version-review" in report.missing_relations_by_case
    assert "HasVersion" not in report.missing_relations_by_case["LC-QA-009-version-review"]
    assert "VersionReviewRequired" not in report.missing_relations_by_case["LC-QA-009-version-review"]


def test_expanded_lc_subset_limits():
    payload = _expanded_subset_result().subset_payload

    assert len(payload.chunks) <= 15
    assert len(payload.entities) <= 30
    assert len(payload.relationships) <= 20
    assert len(payload.chunks) < 291


def test_expanded_lc_subset_uses_case_pack_expectations():
    case = LCBusinessQaCase(
        case_id="LC-QA-EXPECTATION-ONLY",
        level="L2",
        question="Swift Code 和 Bank Internal Code 有什么关系？",
        expected_behavior="按 case expectation 选择对象。",
        expected_answer_points=["Swift Code 与 Bank Internal Code 应来自图谱子集。"],
        expected_entities=["Swift Code", "Bank Internal Code"],
        expected_relations=[],
        expected_domains=["MasterData"],
        expected_sections=["field_table"],
        expected_evidence_keywords=["Swift Code", "Bank Internal Code"],
        expected_graph_coverage="partial",
    )
    subset_result = _expanded_subset_result([case])
    entity_names = {entity.entity_name for entity in subset_result.subset_payload.entities}

    assert "Swift Code" in entity_names
    assert "Bank Internal Code" in entity_names


def test_expanded_lc_subset_endpoint_closure():
    subset_result = _expanded_subset_result()
    entity_names = {entity.entity_name for entity in subset_result.subset_payload.entities}

    assert subset_result.dangling_relationship_count == 0
    assert all(
        relationship.src_id in entity_names and relationship.tgt_id in entity_names
        for relationship in subset_result.subset_payload.relationships
    )


def test_expanded_lc_subset_sidecar_alignment():
    subset_result = _expanded_subset_result()

    assert subset_result.sidecar_alignment_passed is True
    assert len(subset_result.graph_insert_sidecar_records) == (
        subset_result.selected_chunk_count
        + subset_result.selected_entity_count
        + subset_result.selected_relationship_count
    )


def test_expanded_lc_subset_smoke_if_enabled(monkeypatch):
    if os.getenv(ENABLE_LC_SUBSET_SMOKE_ENV) == "1":
        report = run_lc_subset_graph_smoke(enabled=True)
        assert report.neo4j_connected is False
        assert report.cleanup_passed is True
        assert report.selected_chunk_count <= 15
        assert report.selected_entity_count <= 30
        assert report.selected_relationship_count <= 20
        return

    monkeypatch.delenv(ENABLE_LC_SUBSET_SMOKE_ENV, raising=False)
    report = run_lc_subset_graph_smoke(enabled=False)

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.neo4j_connected is False


def test_lc_business_qa_ab_eval_after_expanded_subset():
    report = run_lc_business_qa_ab_eval(
        mode=MODE_OFFLINE,
        max_cases=10,
        use_expanded_subset=True,
    )

    assert report.inconclusive_count <= 3
    assert report.degraded_count == 0
    assert report.avg_graph_score >= report.avg_text_score
    assert report.avg_unsupported_claim_delta == 0


def test_lc_business_qa_ab_eval_reports_remaining_coverage_gaps():
    report = run_lc_business_qa_ab_eval(
        mode=MODE_OFFLINE,
        max_cases=10,
        use_expanded_subset=True,
    )

    assert report.coverage_report is not None
    assert "HasVersion" not in report.coverage_report.missing_relations_by_case["LC-QA-009-version-review"]
    assert "VersionReviewRequired" not in report.coverage_report.missing_relations_by_case["LC-QA-009-version-review"]


def test_text_only_answer_uses_only_text_context():
    report = run_lc_business_qa_ab_eval(mode=MODE_OFFLINE, max_cases=3)

    assert all(not item.text_answer.graph_path_used for item in report.case_results)
    assert all(not item.text_answer.cited_graph_paths for item in report.case_results)


def test_graph_aware_answer_can_use_graph_path():
    report = run_lc_business_qa_ab_eval(mode=MODE_OFFLINE, max_cases=10)

    assert report.graph_path_used_count >= 1
    assert any(item.graph_answer.graph_path_used for item in report.case_results)


def test_judge_detects_unsupported_claim():
    report = run_lc_business_qa_ab_eval(mode=MODE_OFFLINE, max_cases=1)
    case_result = report.case_results[0]
    answer = AnswerGenerationResult(
        query_id=case_result.case.case_id,
        mode=MODE_GRAPH_AWARE,
        answer_text=(
            f"结论：NonexistentEntity 参与流程。"
            f"{case_result.graph_answer.cited_evidence_ids[0]}"
        ),
        cited_evidence_ids=[case_result.graph_answer.cited_evidence_ids[0]],
    )

    judgement = judge_lc_business_answer(case_result.case, answer, _graph_context(case_result))

    assert judgement.unsupported_claim_count > 0
    assert judgement.result in {"WARN", FAIL}


def test_judge_detects_candidate_as_confirmed():
    report = run_lc_business_qa_ab_eval(mode=MODE_OFFLINE, max_cases=1)
    case_result = report.case_results[0]
    answer = AnswerGenerationResult(
        query_id=case_result.case.case_id,
        mode=MODE_GRAPH_AWARE,
        answer_text=(
            f"结论：该 Candidate 已确认是 Confirmed。"
            f"{case_result.graph_answer.cited_evidence_ids[0]}"
        ),
        cited_evidence_ids=[case_result.graph_answer.cited_evidence_ids[0]],
    )

    judgement = judge_lc_business_answer(case_result.case, answer, _graph_context(case_result))

    assert judgement.candidate_as_confirmed_count > 0
    assert judgement.result == FAIL


def test_judge_detects_invalid_citation():
    report = run_lc_business_qa_ab_eval(mode=MODE_OFFLINE, max_cases=1)
    case_result = report.case_results[0]
    answer = AnswerGenerationResult(
        query_id=case_result.case.case_id,
        mode=MODE_GRAPH_AWARE,
        answer_text="结论：引用不存在证据。EV-bad-99",
        cited_evidence_ids=["EV-bad-99"],
    )

    judgement = judge_lc_business_answer(case_result.case, answer, _graph_context(case_result))

    assert judgement.invalid_citation_count > 0
    assert judgement.result == FAIL


def test_case_outside_graph_coverage_marked_inconclusive():
    outside_case = LCBusinessQaCase(
        case_id="LC-QA-OUTSIDE",
        level="L2",
        question="Nonexistent LC Object 会影响什么？",
        expected_behavior="Mini graph 不覆盖时应标记 inconclusive。",
        expected_answer_points=["Nonexistent LC Object 不在当前 mini graph 中。"],
        expected_entities=["Nonexistent LC Object"],
        expected_relations=["NoSuchRelation"],
        expected_domains=["Workflow"],
        expected_sections=["task_rule"],
        expected_evidence_keywords=["Nonexistent LC Object"],
        expected_graph_coverage="partial",
    )

    report = run_lc_business_qa_ab_eval(cases=[outside_case], mode=MODE_OFFLINE, max_cases=1)

    assert report.inconclusive_count == 1
    assert report.case_results[0].improvement_label == INCONCLUSIVE


def test_no_llm_called_by_default():
    run_lc_business_qa_ab_eval(mode=MODE_OFFLINE, max_cases=2)

    assert get_lc_business_qa_runtime_flags()["llm_called"] is False


def test_no_storage_or_neo4j_in_eval():
    report = run_lc_business_qa_ab_eval(
        mode=MODE_OFFLINE,
        max_cases=2,
        use_expanded_subset=True,
    )

    assert report.storage_written is False
    assert report.neo4j_connected is False


def test_live_mode_requires_env(monkeypatch):
    monkeypatch.delenv("LIGHTRAG_DSL_RUN_LC_QA_LIVE", raising=False)
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return "should not run"

    run_lc_business_qa_ab_eval(mode=MODE_LIVE, max_cases=1, llm_callable=fake_llm)

    assert called["value"] is False
    assert get_lc_business_qa_runtime_flags()["llm_called"] is False


def test_report_serializable():
    report = run_lc_business_qa_ab_eval(mode=MODE_OFFLINE, max_cases=3)

    json.dumps(serialize_lc_business_qa_ab_eval_report(report))


def _expanded_subset_result(cases=None):
    selected_cases = list(cases or default_lc_business_qa_cases())
    candidate_payload = build_lc_mini_kg_payload(
        LcMiniGraphSmokeConfig(
            max_chunks=100,
            max_entities=100,
            max_relationships=100,
        )
    )
    return build_lc_expanded_graph_subset_from_case_pack(
        kg_payload=candidate_payload,
        cases=selected_cases,
        **EXPANDED_LC_SUBSET_LIMITS,
    )


def _graph_context(case_result):
    from lightrag_ext.us_dsl.graph_retrieval_eval import (
        compare_retrieval_results,
        run_graph_aware_retrieval,
        run_text_only_retrieval,
    )
    from lightrag_ext.us_dsl.graph_retrieval_index import build_graph_retrieval_indexes
    from lightrag_ext.us_dsl.graph_retrieval_types import GraphRetrievalQuery
    from lightrag_ext.us_dsl.graph_answer_eval import build_answer_contexts_from_retrieval_results
    from lightrag_ext.us_dsl.graph_retrieval_types import GraphRetrievalEvaluationReport
    from lightrag_ext.us_dsl.kg_metadata_sidecar import build_graph_insert_sidecar_records
    from lightrag_ext.us_dsl.kg_test_graph_write import to_lightrag_custom_kg_input
    from lightrag_ext.us_dsl.lc_mini_graph_smoke import (
        LC_MINI_NAMESPACE,
        build_lc_mini_kg_payload,
    )

    payload = build_lc_mini_kg_payload()
    sidecar = build_graph_insert_sidecar_records(
        payload,
        to_lightrag_custom_kg_input(payload),
        namespace=LC_MINI_NAMESPACE,
    )
    indexes = build_graph_retrieval_indexes(payload, sidecar)
    case = case_result.case
    query = GraphRetrievalQuery(
        query_id=case.case_id,
        query_text=case.question,
        expected_domains=list(case.expected_domains),
        expected_sections=list(case.expected_sections),
        expected_entities=list(case.expected_entities),
        expected_relations=list(case.expected_relations),
        expected_evidence_keywords=list(case.expected_evidence_keywords),
    )
    comparison = compare_retrieval_results(
        query,
        run_text_only_retrieval(query, indexes.text_index),
        run_graph_aware_retrieval(
            query,
            indexes.text_index,
            indexes.node_index,
            indexes.edge_index,
            indexes.path_index,
        ),
    )
    retrieval_report = GraphRetrievalEvaluationReport(
        source="test",
        query_count=1,
        improved_count=1,
        same_count=0,
        degraded_count=0,
        inconclusive_count=0,
        avg_entity_recall_delta=0,
        avg_relation_recall_delta=0,
        avg_evidence_coverage_delta=0,
        avg_source_span_coverage_delta=0,
        avg_graph_path_delta=0,
        recommended_next_step="test",
        comparison_results=[comparison],
    )
    _, graph_contexts = build_answer_contexts_from_retrieval_results(retrieval_report)
    return graph_contexts[0]
