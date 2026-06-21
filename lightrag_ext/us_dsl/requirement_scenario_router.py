from __future__ import annotations

from .harness_types import RequirementInput, RequirementScenarioProfile, ScenarioRouteDecision
from .requirement_scenario_profile import build_requirement_scenario_profile


def route_requirement_scenario(
    requirement: RequirementInput,
    profile: RequirementScenarioProfile | None = None,
) -> ScenarioRouteDecision:
    profile = profile or build_requirement_scenario_profile(requirement)
    if requirement.explicit_scenario_override:
        return ScenarioRouteDecision(
            requirement_id=requirement.requirement_id,
            selected_scenario=requirement.explicit_scenario_override,
            classification_status="MANUAL_OVERRIDE",
            confidence=1.0,
            alternative_scenarios=[],
            profile=profile,
            reason_codes=["manual_override_recorded"],
            manual_override_used=True,
        )
    if profile.evidence_sufficiency_score < 0.35:
        return ScenarioRouteDecision(
            requirement_id=requirement.requirement_id,
            selected_scenario=None,
            classification_status="INSUFFICIENT_EVIDENCE",
            confidence=profile.profile_confidence,
            profile=profile,
            reason_codes=["insufficient_evidence", "missing_retrieval_not_zero_to_one"],
            missing_information=["source_evidence", "trusted_context"],
            clarification_questions=[_question("evidence", "Which source document or feature evidence should be used?")],
        )

    new_capability_signal = _new_capability_signal(profile)
    zero_signal = _zero_to_one_signal(profile)
    many_signal = _one_to_many_signal(profile)
    local_signal = _one_to_one_x_signal(profile)
    active = [scenario for scenario, signal in [("ZERO_TO_ONE", zero_signal), ("ONE_TO_MANY", many_signal), ("ONE_TO_ONE_X", local_signal)] if signal]
    if new_capability_signal and many_signal:
        return _mixed(requirement, profile, ["ZERO_TO_ONE", "ONE_TO_MANY"], "new_capability_and_broad_impact")
    if local_signal and profile.affected_domain_count > 1:
        return _ambiguous(requirement, profile, ["ONE_TO_ONE_X", "ONE_TO_MANY"], "cross_domain_risk_prevents_local_overconfidence")
    if len(active) == 1:
        scenario = active[0]
        return ScenarioRouteDecision(
            requirement_id=requirement.requirement_id,
            selected_scenario=scenario,  # type: ignore[arg-type]
            classification_status="CONFIDENT",
            confidence=_confidence_for(profile, scenario),
            alternative_scenarios=[],
            profile=profile,
            reason_codes=[f"{scenario.lower()}_signals_matched"],
        )
    if active:
        return _ambiguous(requirement, profile, active, "multiple_non_exclusive_signals")
    return _ambiguous(requirement, profile, ["ZERO_TO_ONE", "ONE_TO_MANY", "ONE_TO_ONE_X"], "no_confident_signal")


def _zero_to_one_signal(profile: RequirementScenarioProfile) -> bool:
    low_existing = max(
        profile.existing_feature_coverage,
        profile.existing_semantic_object_coverage,
        profile.existing_code_asset_coverage,
    ) <= 0.35
    return _new_capability_signal(profile) and low_existing


def _new_capability_signal(profile: RequirementScenarioProfile) -> bool:
    return profile.novelty_score >= 0.7 and profile.new_business_object_ratio >= 0.6


def _one_to_many_signal(profile: RequirementScenarioProfile) -> bool:
    target_count = len(profile.primary_change_targets)
    impact = profile.direct_impact_count + profile.indirect_impact_count
    return (
        0 < target_count <= 2
        and profile.existing_semantic_object_coverage >= 0.45
        and (profile.affected_feature_count > 1 or profile.affected_domain_count > 1)
        and (impact >= 3 or profile.graph_path_count >= 2)
    )


def _one_to_one_x_signal(profile: RequirementScenarioProfile) -> bool:
    target_count = len(profile.primary_change_targets)
    impact = profile.direct_impact_count + profile.indirect_impact_count
    return (
        0 < target_count <= 2
        and profile.existing_feature_coverage >= 0.7
        and profile.existing_code_asset_coverage >= 0.65
        and profile.affected_feature_count <= 1
        and profile.affected_domain_count <= 1
        and impact <= 2
        and profile.local_change_score >= 0.65
    )


def _confidence_for(profile: RequirementScenarioProfile, scenario: str) -> float:
    if scenario == "ZERO_TO_ONE":
        return round((profile.novelty_score + profile.new_business_object_ratio + profile.evidence_sufficiency_score) / 3.0, 3)
    if scenario == "ONE_TO_MANY":
        breadth = min(1.0, (profile.affected_feature_count + profile.affected_domain_count + profile.graph_path_count) / 6.0)
        return round((profile.existing_semantic_object_coverage + breadth + profile.evidence_sufficiency_score) / 3.0, 3)
    return round((profile.existing_feature_coverage + profile.existing_code_asset_coverage + profile.local_change_score) / 3.0, 3)


def _mixed(requirement: RequirementInput, profile: RequirementScenarioProfile, alternatives: list[str], reason: str) -> ScenarioRouteDecision:
    return ScenarioRouteDecision(
        requirement_id=requirement.requirement_id,
        selected_scenario=None,
        classification_status="MIXED",
        confidence=profile.profile_confidence,
        alternative_scenarios=alternatives,  # type: ignore[arg-type]
        profile=profile,
        reason_codes=[reason],
        clarification_questions=[_question("split", "Should this be split into separate new capability and impact-change requests?")],
    )


def _ambiguous(requirement: RequirementInput, profile: RequirementScenarioProfile, alternatives: list[str], reason: str) -> ScenarioRouteDecision:
    return ScenarioRouteDecision(
        requirement_id=requirement.requirement_id,
        selected_scenario=None,
        classification_status="AMBIGUOUS",
        confidence=profile.profile_confidence,
        alternative_scenarios=alternatives,  # type: ignore[arg-type]
        profile=profile,
        reason_codes=[reason],
        clarification_questions=[_question("scope", "Please clarify scope, evidence, and expected output boundary.")],
    )


def _question(question_id: str, text: str) -> dict[str, str]:
    return {"question_id": question_id, "question": text}
