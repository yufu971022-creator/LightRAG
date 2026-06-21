from __future__ import annotations

import json

from lightrag_ext.us_dsl.lc_us_generation_cases import (
    default_lc_us_generation_cases,
)
from lightrag_ext.us_dsl.lc_us_generation_eval import (
    LIVE_LC_US_GENERATION_ENV,
    MODE_LIVE,
    MODE_OFFLINE,
    get_lc_us_generation_runtime_flags,
    run_lc_us_generation_ab_eval,
    serialize_us_generation_ab_eval_report,
)
from lightrag_ext.us_dsl.graph_answer_types import GraphAnswerEvaluationReport
from lightrag_ext.us_dsl.us_generation_types import USGenerationAbEvalReport


def test_lc_us_generation_cases_defined():
    cases = default_lc_us_generation_cases()

    assert len(cases) >= 6
    for case in cases:
        assert case.user_request
        assert case.expected_us_sections
        assert case.grading_notes


def test_expected_sections_are_not_generated_from_agent_output():
    cases = default_lc_us_generation_cases()

    assert all("evidence_id" not in " ".join(case.expected_us_sections) for case in cases)
    assert all("graph-aware" not in case.grading_notes.lower() for case in cases)


def test_text_only_us_generation_uses_only_text_context():
    report = run_lc_us_generation_ab_eval(mode=MODE_OFFLINE, max_cases=4)

    assert all(not item.text_result.graph_path_used for item in report.case_results)
    assert all(not item.text_result.cited_graph_paths for item in report.case_results)


def test_graph_aware_us_generation_can_use_graph_path():
    report = run_lc_us_generation_ab_eval(mode=MODE_OFFLINE, max_cases=8)

    assert report.graph_path_used_count >= 1
    assert any(item.graph_result.graph_path_used for item in report.case_results)


def test_version_uncertain_case_is_not_forced_pass():
    report = run_lc_us_generation_ab_eval(mode=MODE_OFFLINE, max_cases=8)
    version_case = [
        item for item in report.case_results if item.case.generation_task_type == "VERSION_REVIEW_US"
    ][0]

    assert version_case.graph_coverage_status != "none"
    assert "HasVersion" not in version_case.missing_graph_objects
    assert "VersionReviewRequired" not in version_case.missing_graph_objects
    assert "Open Questions / To Be Confirmed" in version_case.graph_result.generated_us_markdown
    assert "人工确认" in version_case.graph_result.generated_us_markdown
    assert version_case.graph_judgement.adoption_level != "ACCEPT_AS_IS"


def test_run_lc_us_generation_ab_eval_offline():
    report = run_lc_us_generation_ab_eval(mode=MODE_OFFLINE, max_cases=8)

    assert report.case_count > 0
    assert report.avg_graph_score >= report.avg_text_score
    assert report.degraded_count == 0
    assert report.avg_unsupported_claim_delta == 0


def test_no_llm_called_by_default():
    run_lc_us_generation_ab_eval(mode=MODE_OFFLINE, max_cases=2)

    assert get_lc_us_generation_runtime_flags()["llm_called"] is False


def test_live_mode_requires_env(monkeypatch):
    monkeypatch.delenv(LIVE_LC_US_GENERATION_ENV, raising=False)
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return "should not run"

    run_lc_us_generation_ab_eval(
        mode=MODE_LIVE,
        max_cases=1,
        llm_callable=fake_llm,
    )

    assert called["value"] is False
    assert get_lc_us_generation_runtime_flags()["llm_called"] is False


def test_no_storage_or_neo4j():
    report = run_lc_us_generation_ab_eval(mode=MODE_OFFLINE, max_cases=2)

    assert report.storage_written is False
    assert report.neo4j_connected is False


def test_report_serializable():
    report = run_lc_us_generation_ab_eval(mode=MODE_OFFLINE, max_cases=3)

    json.dumps(serialize_us_generation_ab_eval_report(report))


def test_not_block_19b():
    report = run_lc_us_generation_ab_eval(mode=MODE_OFFLINE, max_cases=2)
    serialized = serialize_us_generation_ab_eval_report(report)

    assert isinstance(report, USGenerationAbEvalReport)
    assert not isinstance(report, GraphAnswerEvaluationReport)
    assert "accept_as_is_count" in serialized
    assert "accept_with_minor_edits_count" in serialized
    assert "need_major_revision_count" in serialized
    assert "reject_count" in serialized
    assert "avg_answer_completeness_delta" not in serialized
    assert report.case_results
    assert report.case_results[0].text_result.generated_us_markdown
    assert "Source Evidence" in report.case_results[0].text_result.generated_us_markdown
