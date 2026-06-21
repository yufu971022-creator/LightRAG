from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.ab_result_comparator import compare_ab_results
from lightrag_ext.us_dsl.gold_case_validator import load_cases_for_manifest
from lightrag_ext.us_dsl.retrieval_performance_metrics import build_performance_metrics
from lightrag_ext.us_dsl.tests.multi_module_eval_test_helpers import hit_for, results_for, write_manifest_tree


def _perf(ingestion: float = 100.0, p95: float = 10.0):
    return build_performance_metrics(
        ingestion_time_ms=ingestion,
        measured_query_runs_ms=[p95, p95, p95, p95, p95],
        warmup_latency_ms=1.0,
        embedding_call_count=1,
        llm_call_count=1,
        storage_size_bytes=1000,
    )


def test_overall_average_cannot_hide_module_regression(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    report = compare_ab_results(
        manifest=manifest,
        cases=cases,
        baseline_results=results_for(cases, group="baseline"),
        candidate_results=results_for(cases, group="candidate", missing_module="MOD1"),
        baseline_performance=_perf(),
        candidate_performance=_perf(),
    )
    assert "MODULE_RECALL_REGRESSION" in report.overall_decision.failed_primary_gates
    assert report.overall_decision.overall_status == "FAIL_MODULE_REGRESSION"


def test_holdout_has_separate_gate(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    report = compare_ab_results(
        manifest=manifest,
        cases=cases,
        baseline_results=results_for(cases, group="baseline"),
        candidate_results=results_for(cases, group="candidate", missing_module="MOD3"),
        baseline_performance=_perf(),
        candidate_performance=_perf(),
    )
    assert report.overall_decision.overall_status == "FAIL_HOLDOUT_GENERALIZATION"


def test_1_to_n_cases_have_separate_metrics(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    object.__setattr__(cases[0], "one_to_n", True)
    baseline = [hit_for(cases[0], group="baseline", missing=True)] + results_for(cases[1:], group="baseline")
    candidate = results_for(cases, group="candidate")
    report = compare_ab_results(
        manifest=manifest,
        cases=cases,
        baseline_results=baseline,
        candidate_results=candidate,
        baseline_performance=_perf(),
        candidate_performance=_perf(),
    )
    assert report.one_to_n_improved_count >= 1


def test_candidate_raw_recall_regression_threshold(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    report = compare_ab_results(
        manifest=manifest,
        cases=cases,
        baseline_results=results_for(cases, group="baseline"),
        candidate_results=results_for(cases, group="candidate", missing_module="MOD0"),
        baseline_performance=_perf(),
        candidate_performance=_perf(),
    )
    assert "OVERALL_EVIDENCE_RECALL_REGRESSION" in report.overall_decision.failed_primary_gates


def test_per_module_regression_threshold(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    report = compare_ab_results(
        manifest=manifest,
        cases=cases,
        baseline_results=results_for(cases, group="baseline"),
        candidate_results=results_for(cases, group="candidate", missing_module="MOD2"),
        baseline_performance=_perf(),
        candidate_performance=_perf(),
    )
    assert any(not item.passed for item in report.per_module)


def test_primary_gate_is_deterministic(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    first = compare_ab_results(
        manifest=manifest,
        cases=cases,
        baseline_results=results_for(cases, group="baseline"),
        candidate_results=results_for(cases, group="candidate"),
        baseline_performance=_perf(),
        candidate_performance=_perf(),
    )
    second = compare_ab_results(
        manifest=manifest,
        cases=cases,
        baseline_results=results_for(cases, group="baseline"),
        candidate_results=results_for(cases, group="candidate"),
        baseline_performance=_perf(),
        candidate_performance=_perf(),
    )
    assert first.overall_decision == second.overall_decision


def test_llm_judge_is_not_primary_gate(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    report = compare_ab_results(
        manifest=manifest,
        cases=cases,
        baseline_results=results_for(cases, group="baseline"),
        candidate_results=results_for(cases, group="candidate"),
        baseline_performance=_perf(),
        candidate_performance=_perf(),
        primary_eval_uses_llm_judge=True,
    )
    assert "LLM_JUDGE_USED_AS_PRIMARY" in report.overall_decision.failed_primary_gates
