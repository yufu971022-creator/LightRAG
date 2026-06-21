from __future__ import annotations

from dataclasses import replace

from .design_quality_types import FunctionalQAResult, ImpactAnalysisResult, QualityGateResult, RepairAction, RepairPlan

_ACTION_BY_ERROR = {
    "MISSING_CITATION": "FIX_CITATION",
    "INVALID_CITATION": "FIX_CITATION",
    "UNSUPPORTED_FACT": "REMOVE_UNSUPPORTED_CLAIM",
    "UNSUPPORTED_PATH": "DOWNGRADE_TO_TENTATIVE",
    "VERSION_HARD_JUDGMENT": "ADD_VERSION_WARNING",
    "HISTORICAL_AS_CURRENT": "ADD_VERSION_WARNING",
    "UNSAFE_FACT_PROMOTION": "REMOVE_UNSUPPORTED_CLAIM",
    "MISSING_RELEVANT_DIMENSION": "ADD_MISSING_RELEVANT_DIMENSION",
    "DUPLICATE_IMPACT": "MERGE_DUPLICATE_IMPACT",
    "FALSE_POSITIVE_IMPACT": "REMOVE_IRRELEVANT_IMPACT",
    "INSUFFICIENT_EVIDENCE_NOT_REPORTED": "RETURN_INSUFFICIENT_EVIDENCE",
}


def plan_targeted_repair(case_id: str, gate_results: list[QualityGateResult], *, attempt_number: int, max_attempts: int = 2) -> RepairPlan:
    if attempt_number >= max_attempts:
        return RepairPlan(case_id, attempt_number, [], max_attempts=max_attempts)
    actions: list[RepairAction] = []
    seen: set[tuple[str, str]] = set()
    for gate in gate_results:
        for error in gate.errors:
            action_type = _ACTION_BY_ERROR.get(error, "RETURN_INSUFFICIENT_EVIDENCE")
            key = (gate.gate_name, action_type)
            if key in seen:
                continue
            seen.add(key)
            actions.append(
                RepairAction(
                    action_id=f"repair_{len(actions) + 1}",
                    action_type=action_type,
                    target_gate=gate.gate_name,
                    reason_code=error,
                    description="Target only the failed deterministic quality gate; do not rerun the full chain.",
                )
            )
    return RepairPlan(case_id, attempt_number + 1, actions, max_attempts=max_attempts)


def apply_repair(output: FunctionalQAResult | ImpactAnalysisResult, plan: RepairPlan):
    action_types = {item.action_type for item in plan.actions}
    if isinstance(output, FunctionalQAResult):
        supporting_facts = output.supporting_facts
        status = output.answer_status
        safe = output.safe_for_business_use
        version_context = dict(output.version_context)
        if "REMOVE_UNSUPPORTED_CLAIM" in action_types:
            supporting_facts = [fact for fact in supporting_facts if fact.evidence_refs and fact.fact_kind == "FACT"]
        if "ADD_VERSION_WARNING" in action_types:
            version_context["resolution_status"] = "VERSION_REVIEW_REQUIRED"
            version_context["version_warnings"] = ["current rule requires review"]
            status = "ANSWERED_WITH_VERSION_WARNING"
            safe = False
        if "RETURN_INSUFFICIENT_EVIDENCE" in action_types:
            status = "INSUFFICIENT_EVIDENCE"
            safe = False
        return replace(output, supporting_facts=supporting_facts, answer_status=status, safe_for_business_use=safe, version_context=version_context)
    direct = output.direct_impacts
    indirect = output.indirect_impacts
    tentative = list(output.tentative_impacts)
    if "REMOVE_IRRELEVANT_IMPACT" in action_types:
        direct = [item for item in direct if item.candidate_kind == "FACT"]
        indirect = [item for item in indirect if item.candidate_kind == "FACT"]
    if "DOWNGRADE_TO_TENTATIVE" in action_types:
        direct = [item for item in direct if item.evidence_refs]
        indirect = [item for item in indirect if item.evidence_refs]
    if "MERGE_DUPLICATE_IMPACT" in action_types:
        direct = _dedupe(direct)
        indirect = _dedupe(indirect)
        tentative = _dedupe(tentative)
    return replace(output, direct_impacts=direct, indirect_impacts=indirect, tentative_impacts=tentative)


def _dedupe(items):
    seen = set()
    deduped = []
    for item in items:
        if item.affected_object_id in seen:
            continue
        seen.add(item.affected_object_id)
        deduped.append(item)
    return deduped
