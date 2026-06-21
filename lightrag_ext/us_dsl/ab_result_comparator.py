from __future__ import annotations

from .multi_module_eval_types import (
    AbComparisonReport,
    AbGateDecision,
    CaseRetrievalResult,
    EffectivenessMetrics,
    EvaluationCase,
    ModuleComparison,
    MultiModuleManifest,
    PerformanceMetrics,
)
from .retrieval_effectiveness_metrics import compute_effectiveness_metrics, compute_per_module_effectiveness
from .retrieval_performance_metrics import performance_passes_policy, performance_ratios
from .retrieval_safety_metrics import compute_retrieval_safety_metrics, safety_passes_primary_gate


def compare_ab_results(
    *,
    manifest: MultiModuleManifest,
    cases: list[EvaluationCase],
    baseline_results: list[CaseRetrievalResult],
    candidate_results: list[CaseRetrievalResult],
    baseline_performance: PerformanceMetrics,
    candidate_performance: PerformanceMetrics,
    primary_eval_uses_llm_judge: bool = False,
) -> AbComparisonReport:
    baseline_overall = compute_effectiveness_metrics(cases, baseline_results)
    candidate_overall = compute_effectiveness_metrics(cases, candidate_results)
    baseline_by_module = compute_per_module_effectiveness(cases, baseline_results)
    candidate_by_module = compute_per_module_effectiveness(cases, candidate_results)
    split_by_module = {module.module_code: module.split for module in manifest.modules}
    per_module: list[ModuleComparison] = []
    for module_code in sorted(baseline_by_module):
        baseline_metrics = baseline_by_module[module_code]
        candidate_metrics = candidate_by_module.get(module_code, _empty_metrics())
        recall_delta = candidate_metrics.evidence_recall_at_k - baseline_metrics.evidence_recall_at_k
        relation_delta = candidate_metrics.relation_recall_at_k - baseline_metrics.relation_recall_at_k
        dimension_delta = candidate_metrics.required_dimension_coverage - baseline_metrics.required_dimension_coverage
        passed = recall_delta >= -manifest.policy.max_per_module_recall_regression
        per_module.append(
            ModuleComparison(
                module_code=module_code,
                split=split_by_module.get(module_code, "CALIBRATION"),
                baseline_metrics=baseline_metrics,
                candidate_metrics=candidate_metrics,
                recall_delta=recall_delta,
                relation_delta=relation_delta,
                dimension_delta=dimension_delta,
                passed=passed,
            )
        )
    holdout = [item for item in per_module if item.split == "HOLDOUT"]
    safety = compute_retrieval_safety_metrics(candidate_results)
    one_to_n_cases = {case.case_id for case in cases if case.one_to_n}
    improved = 0
    degraded = 0
    for case_id in one_to_n_cases:
        baseline_case = compute_effectiveness_metrics([case for case in cases if case.case_id == case_id], [result for result in baseline_results if result.case_id == case_id])
        candidate_case = compute_effectiveness_metrics([case for case in cases if case.case_id == case_id], [result for result in candidate_results if result.case_id == case_id])
        delta = (candidate_case.relation_recall_at_k + candidate_case.required_dimension_coverage) - (
            baseline_case.relation_recall_at_k + baseline_case.required_dimension_coverage
        )
        if delta > 0:
            improved += 1
        elif delta < 0:
            degraded += 1
    failed_gates = _failed_gates(
        manifest=manifest,
        baseline=baseline_overall,
        candidate=candidate_overall,
        per_module=per_module,
        holdout=holdout,
        safety=safety,
        baseline_performance=baseline_performance,
        candidate_performance=candidate_performance,
        primary_eval_uses_llm_judge=primary_eval_uses_llm_judge,
    )
    decision = _decision_from_failures(failed_gates)
    return AbComparisonReport(
        overall_decision=decision,
        baseline_overall=baseline_overall,
        candidate_overall=candidate_overall,
        per_module=per_module,
        holdout=holdout,
        one_to_n_improved_count=improved,
        one_to_n_degraded_count=degraded,
        safety=safety,
        performance={
            "ratios": performance_ratios(baseline_performance, candidate_performance),
            "baseline": baseline_performance,
            "candidate": candidate_performance,
        },
    )


def _failed_gates(
    *,
    manifest: MultiModuleManifest,
    baseline: EffectivenessMetrics,
    candidate: EffectivenessMetrics,
    per_module: list[ModuleComparison],
    holdout: list[ModuleComparison],
    safety: object,
    baseline_performance: PerformanceMetrics,
    candidate_performance: PerformanceMetrics,
    primary_eval_uses_llm_judge: bool,
) -> list[str]:
    failures: list[str] = []
    if candidate.evidence_recall_at_k < baseline.evidence_recall_at_k - manifest.policy.max_raw_recall_regression:
        failures.append("OVERALL_EVIDENCE_RECALL_REGRESSION")
    if any(not item.passed for item in per_module):
        failures.append("MODULE_RECALL_REGRESSION")
    if holdout and any(not item.passed for item in holdout):
        failures.append("HOLDOUT_REGRESSION")
    if not safety_passes_primary_gate(safety):  # type: ignore[arg-type]
        failures.append("SAFETY_GATE_FAILED")
    if not performance_passes_policy(baseline_performance, candidate_performance, manifest.policy):
        failures.append("PERFORMANCE_GATE_FAILED")
    if primary_eval_uses_llm_judge:
        failures.append("LLM_JUDGE_USED_AS_PRIMARY")
    return failures


def _decision_from_failures(failures: list[str]) -> AbGateDecision:
    if not failures:
        return AbGateDecision("PASS", [], "none", "Block 27A")
    if "HOLDOUT_REGRESSION" in failures:
        status = "FAIL_HOLDOUT_GENERALIZATION"
    elif "MODULE_RECALL_REGRESSION" in failures:
        status = "FAIL_MODULE_REGRESSION"
    elif "SAFETY_GATE_FAILED" in failures:
        status = "FAIL_SAFETY"
    elif "PERFORMANCE_GATE_FAILED" in failures:
        status = "FAIL_PERFORMANCE"
    else:
        status = "FAIL_EFFECTIVENESS"
    return AbGateDecision(status, failures, "Inspect failed gates before changing policy or gold data.", "Stay in Block 26B")


def _empty_metrics() -> EffectivenessMetrics:
    return EffectivenessMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
