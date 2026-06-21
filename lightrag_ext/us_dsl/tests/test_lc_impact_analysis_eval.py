from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.impact_analysis_types import MODE_GRAPH_AWARE
from lightrag_ext.us_dsl.lc_impact_analysis_cases import (
    default_lc_impact_analysis_cases,
)
from lightrag_ext.us_dsl.lc_impact_analysis_eval import (
    LIVE_LC_IMPACT_ANALYSIS_ENV,
    MODE_LIVE,
    MODE_OFFLINE,
    get_lc_impact_analysis_runtime_flags,
    run_lc_impact_analysis_ab_eval,
    serialize_impact_analysis_ab_eval_report,
)
from lightrag_ext.us_dsl.impact_analysis_judge import judge_impact_analysis
from lightrag_ext.us_dsl.impact_analysis_types import ImpactAnalysisResult


def test_lc_impact_cases_defined():
    cases = default_lc_impact_analysis_cases()

    assert len(cases) >= 6
    for case in cases:
        assert case.change_request
        assert case.expected_impact_dimensions
        assert case.grading_notes


def test_lc_impact_cases_are_case_pack_not_evaluator_logic():
    root = Path(__file__).resolve().parents[1]
    forbidden_terms = [
        "LCAB",
        "Acceptable Bank",
        "可接受银行",
        "Bank Status",
        "Swift Code",
        "Transfer To",
    ]
    for relative_path in ["impact_analysis_eval.py", "impact_analysis_judge.py"]:
        text = (root / relative_path).read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text


def test_run_lc_impact_analysis_ab_eval_offline():
    report = run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=6)

    assert report.case_count == 6
    assert report.avg_graph_score >= report.avg_text_score
    assert report.improved_count >= 4
    assert report.degraded_count == 0
    assert report.avg_unsupported_claim_delta == 0


def test_text_only_impact_uses_no_graph_path():
    report = run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=3)

    assert all(not item.text_result.graph_path_used for item in report.case_results)
    assert all(not item.text_result.cited_graph_paths for item in report.case_results)


def test_graph_aware_impact_uses_graph_path():
    report = run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=6)

    assert report.graph_path_used_count >= 1
    assert any(item.graph_result.graph_path_used for item in report.case_results)


def test_graph_aware_impact_covers_more_relations():
    report = run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=6)

    assert report.avg_relation_path_delta > 0


def test_version_impact_keeps_manual_review():
    report = run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=6)
    version_case = [
        item for item in report.case_results if item.case.impact_task_type == "VERSION_IMPACT"
    ][0]

    assert version_case.graph_coverage_status != "none"
    assert "HasVersion" not in version_case.missing_graph_objects
    assert "VersionReviewRequired" not in version_case.missing_graph_objects
    assert "Open Questions / To Be Confirmed" in version_case.graph_result.analysis_markdown
    assert "人工确认" in version_case.graph_result.analysis_markdown


def test_judge_detects_unsupported_claim():
    report = run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=1)
    case_result = report.case_results[0]
    result = ImpactAnalysisResult(
        case_id=case_result.case.case_id,
        mode=MODE_GRAPH_AWARE,
        analysis_markdown="NonexistentEntity 会产生影响。EV-graph_aware-01",
        cited_evidence_ids=["EV-graph_aware-01"],
    )

    judgement = judge_impact_analysis(case_result.case, result, _graph_context(case_result))

    assert judgement.unsupported_claim_count > 0


def test_no_llm_called_by_default():
    run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=2)

    assert get_lc_impact_analysis_runtime_flags()["llm_called"] is False


def test_live_mode_requires_env(monkeypatch):
    monkeypatch.delenv(LIVE_LC_IMPACT_ANALYSIS_ENV, raising=False)
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return "should not run"

    run_lc_impact_analysis_ab_eval(
        mode=MODE_LIVE,
        max_cases=1,
        llm_callable=fake_llm,
    )

    assert called["value"] is False
    assert get_lc_impact_analysis_runtime_flags()["llm_called"] is False


def test_no_storage_or_neo4j():
    report = run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=2)

    assert report.storage_written is False
    assert report.neo4j_connected is False


def test_report_serializable():
    report = run_lc_impact_analysis_ab_eval(mode=MODE_OFFLINE, max_cases=6)

    json.dumps(serialize_impact_analysis_ab_eval_report(report))


def _graph_context(case_result):
    from lightrag_ext.us_dsl.graph_answer_types import EvidenceItem, GraphAnswerContext

    return GraphAnswerContext(
        query_id=case_result.case.case_id,
        query_text=case_result.case.change_request,
        mode=MODE_GRAPH_AWARE,
        evidence_items=[
            EvidenceItem(
                evidence_id="EV-graph_aware-01",
                source_us_id="US-LCAB-001",
                text_unit_id="tu-1",
                source_span={"start": 0, "end": 20},
                text_hash="hash-1",
                evidence_text="Supported evidence.",
                feature_key="FeatureA",
                domain_code="Workflow",
                section_type="task_rule",
                from_graph=True,
            )
        ],
        expected_entities=list(case_result.case.expected_entities),
        expected_relations=list(case_result.case.expected_relations),
    )
