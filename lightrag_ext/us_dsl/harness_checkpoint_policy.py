from __future__ import annotations

from .harness_types import CheckpointResult, HarnessContext, HarnessExecutionPlan


def required_checkpoint_types_for_scenario(scenario: str | None) -> list[str]:
    if scenario == "ZERO_TO_ONE":
        return ["EVIDENCE_CHECK", "CLARIFICATION_CHECK", "HUMAN_DECISION_REQUIRED"]
    if scenario == "ONE_TO_MANY":
        return ["VERSION_CHECK", "IMPACT_BREADTH_CHECK", "EVIDENCE_CHECK"]
    if scenario == "ONE_TO_ONE_X":
        return ["EVIDENCE_CHECK", "IMPACT_BREADTH_CHECK", "CAPABILITY_CHECK"]
    return ["CLARIFICATION_CHECK"]


def evaluate_harness_checkpoints(context: HarnessContext, plan: HarnessExecutionPlan | None = None) -> list[CheckpointResult]:
    scenario = context.scenario_route.selected_scenario
    results: list[CheckpointResult] = []
    for checkpoint_type in required_checkpoint_types_for_scenario(scenario):
        if checkpoint_type == "EVIDENCE_CHECK":
            passed = context.scenario_profile.evidence_sufficiency_score >= 0.35 and bool(context.source_evidence)
            results.append(
                CheckpointResult(
                    checkpoint_type="EVIDENCE_CHECK",
                    passed=passed,
                    blocks_downstream=not passed,
                    reason_codes=[] if passed else ["insufficient_source_evidence"],
                    required_clarifications=[] if passed else context.open_questions,
                )
            )
        elif checkpoint_type == "VERSION_CHECK":
            passed = bool(context.version_context.get("safe_for_deterministic_answer", True))
            results.append(CheckpointResult("VERSION_CHECK", passed, not passed, [] if passed else ["version_context_not_safe"]))
        elif checkpoint_type == "IMPACT_BREADTH_CHECK":
            if scenario == "ONE_TO_ONE_X":
                passed = context.scenario_profile.affected_domain_count <= 1 and context.scenario_profile.affected_feature_count <= 1
                reason = [] if passed else ["local_scope_not_proven"]
            else:
                passed = context.scenario_profile.affected_domain_count > 1 or context.scenario_profile.affected_feature_count > 1
                reason = [] if passed else ["impact_breadth_not_proven"]
            results.append(CheckpointResult("IMPACT_BREADTH_CHECK", passed, not passed, reason))
        elif checkpoint_type == "CAPABILITY_CHECK":
            has_blocking_gap = bool(plan and plan.blocking_gaps)
            code_available = context.available_code_context.get("status") == "AVAILABLE"
            passed = code_available and not has_blocking_gap
            results.append(
                CheckpointResult(
                    checkpoint_type="CAPABILITY_CHECK",
                    passed=passed,
                    blocks_downstream=not passed,
                    reason_codes=[] if passed else ["code_context_capability_gap"],
                )
            )
        elif checkpoint_type == "CLARIFICATION_CHECK":
            needs = context.scenario_route.classification_status in {"AMBIGUOUS", "MIXED", "INSUFFICIENT_EVIDENCE"}
            results.append(
                CheckpointResult(
                    checkpoint_type="CLARIFICATION_CHECK",
                    passed=not needs,
                    blocks_downstream=needs,
                    reason_codes=[] if not needs else ["clarification_required"],
                    required_clarifications=context.open_questions,
                )
            )
        elif checkpoint_type == "HUMAN_DECISION_REQUIRED":
            results.append(
                CheckpointResult(
                    checkpoint_type="HUMAN_DECISION_REQUIRED",
                    passed=True,
                    blocks_downstream=False,
                    reason_codes=["assumption_checkpoint_required"],
                )
            )
    return results


def has_blocking_checkpoint(results: list[CheckpointResult]) -> bool:
    return any(not result.passed and result.blocks_downstream for result in results)
