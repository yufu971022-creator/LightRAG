from __future__ import annotations

from .harness_types import RequirementScenario, SkillCapabilityStatus, SkillContract

REQUIRED_SKILL_IDS = [
    "REQUIREMENT_INTAKE",
    "SCENARIO_CLASSIFICATION",
    "CLARIFICATION_QUESTION_GENERATION",
    "TRUSTED_KNOWLEDGE_RETRIEVAL",
    "VERSION_ANALYSIS",
    "NOVELTY_GAP_ANALYSIS",
    "CURRENT_STATE_ANALYSIS",
    "PRIMARY_CHANGE_TARGET_IDENTIFICATION",
    "FEATURE_DECOMPOSITION",
    "FUNCTION_DECOMPOSITION",
    "IMPACT_ANALYSIS",
    "HIGH_LEVEL_SOLUTION_PLANNING",
    "DETAILED_DESIGN_PLANNING",
    "UX_DESIGN_INPUT_PLANNING",
    "FIELD_SPEC_PLANNING",
    "PROCESS_STATE_DESIGN_PLANNING",
    "INTEGRATION_DESIGN_PLANNING",
    "PERMISSION_AUDIT_DESIGN_PLANNING",
    "MIGRATION_INITIALIZATION_PLANNING",
    "DFX_DESIGN_PLANNING",
    "US_GENERATION",
    "AC_GENERATION",
    "TEST_SCOPE_PLANNING",
    "CODE_CONTEXT_HANDOFF",
    "CROSS_OUTPUT_CONSISTENCY_CHECK",
    "FINAL_QUALITY_GATE",
]

EXTRA_GENERIC_SKILL_IDS = ["LOCAL_IMPACT_CHECK"]
ALL_SKILL_IDS = [*REQUIRED_SKILL_IDS, *EXTRA_GENERIC_SKILL_IDS]

ADAPTER_SKILL_IDS = {
    "TRUSTED_KNOWLEDGE_RETRIEVAL",
    "VERSION_ANALYSIS",
    "IMPACT_ANALYSIS",
    "US_GENERATION",
}
PLANNED_SKILL_IDS = {"UX_DESIGN_INPUT_PLANNING", "CODE_CONTEXT_HANDOFF"}
FUTURE_LLM_SKILL_IDS = {
    "HIGH_LEVEL_SOLUTION_PLANNING",
    "DETAILED_DESIGN_PLANNING",
    "US_GENERATION",
    "AC_GENERATION",
    "CROSS_OUTPUT_CONSISTENCY_CHECK",
    "FINAL_QUALITY_GATE",
}

ALL_SCENARIOS: list[RequirementScenario] = ["ZERO_TO_ONE", "ONE_TO_MANY", "ONE_TO_ONE_X"]


def build_skill_contracts() -> dict[str, SkillContract]:
    return {skill_id: _contract(skill_id) for skill_id in ALL_SKILL_IDS}


def _contract(skill_id: str) -> SkillContract:
    status = _capability_status(skill_id)
    return SkillContract(
        skill_id=skill_id,
        name=skill_id.replace("_", " ").title(),
        description=_description(skill_id),
        capability_status=status,
        supported_scenarios=_supported_scenarios(skill_id),
        required_inputs=_required_inputs(skill_id),
        optional_inputs=["term_context", "type_context", "version_context", "impact_context"],
        output_schema=_output_schema(skill_id),
        preconditions=_preconditions(skill_id),
        postconditions=_postconditions(skill_id),
        failure_modes=_failure_modes(skill_id),
        checkpoint_after=skill_id in {"SCENARIO_CLASSIFICATION", "VERSION_ANALYSIS", "IMPACT_ANALYSIS", "CODE_CONTEXT_HANDOFF", "FINAL_QUALITY_GATE"},
        side_effect_policy="NO_SIDE_EFFECTS_OR_STORAGE_WRITES",
        adapter_target=_adapter_target(skill_id),
    )


def _capability_status(skill_id: str) -> SkillCapabilityStatus:
    if skill_id in ADAPTER_SKILL_IDS:
        return "ADAPTER_AVAILABLE"
    if skill_id in PLANNED_SKILL_IDS:
        return "PLANNED_NOT_IMPLEMENTED"
    return "AVAILABLE"


def _supported_scenarios(skill_id: str) -> list[RequirementScenario]:
    if skill_id == "NOVELTY_GAP_ANALYSIS":
        return ["ZERO_TO_ONE"]
    if skill_id in {"VERSION_ANALYSIS", "IMPACT_ANALYSIS"}:
        return ["ONE_TO_MANY", "ONE_TO_ONE_X"]
    if skill_id in {"LOCAL_IMPACT_CHECK", "CODE_CONTEXT_HANDOFF"}:
        return ["ONE_TO_ONE_X"]
    return list(ALL_SCENARIOS)


def _required_inputs(skill_id: str) -> list[str]:
    common = ["requirement_input", "scenario_route"]
    if skill_id == "SCENARIO_CLASSIFICATION":
        return ["requirement_input", "scenario_profile"]
    if skill_id == "TRUSTED_KNOWLEDGE_RETRIEVAL":
        return ["requirement_input", "scenario_profile"]
    if skill_id == "VERSION_ANALYSIS":
        return [*common, "trusted_context_pack"]
    if skill_id == "IMPACT_ANALYSIS":
        return [*common, "trusted_context_pack", "version_context"]
    if skill_id == "CODE_CONTEXT_HANDOFF":
        return [*common, "code_context_adapter"]
    if skill_id == "US_GENERATION":
        return [*common, "trusted_context_pack", "version_context", "impact_context", "design_task_pack"]
    return [*common, "harness_context"]


def _output_schema(skill_id: str) -> dict[str, object]:
    if skill_id == "US_GENERATION":
        return {"type": "object", "properties": {"task_spec": "dict", "final_us_generated": False}}
    if skill_id == "CODE_CONTEXT_HANDOFF":
        return {"type": "object", "properties": {"code_context_status": "string", "handoff_contract": "dict"}}
    return {"type": "object", "properties": {"skill_id": skill_id, "status": "string", "evidence_refs": "list"}}


def _preconditions(skill_id: str) -> list[str]:
    preconditions = ["scenario_route_available", "context_contract_available"]
    if skill_id == "CODE_CONTEXT_HANDOFF":
        preconditions.append("code_context_adapter_configured")
    if skill_id == "FINAL_QUALITY_GATE":
        preconditions.append("all_prior_outputs_marked_as_plan_or_dry_run")
    return preconditions


def _postconditions(skill_id: str) -> list[str]:
    if skill_id in FUTURE_LLM_SKILL_IDS:
        return ["future_execution_contract_recorded", "no_final_business_text_generated"]
    if skill_id == "CODE_CONTEXT_HANDOFF":
        return ["code_context_availability_recorded", "capability_gap_visible_when_missing"]
    return ["trace_event_recorded", "outputs_match_contract"]


def _failure_modes(skill_id: str) -> list[str]:
    modes = ["INSUFFICIENT_EVIDENCE", "MISSING_REQUIRED_CONTEXT"]
    if skill_id in PLANNED_SKILL_IDS:
        modes.append("CAPABILITY_NOT_IMPLEMENTED")
    if skill_id in ADAPTER_SKILL_IDS:
        modes.append("ADAPTER_UNAVAILABLE")
    return modes


def _adapter_target(skill_id: str) -> str | None:
    targets = {
        "TRUSTED_KNOWLEDGE_RETRIEVAL": "lightrag_ext.us_dsl.hybrid_retrieval_service:HybridRetrievalService",
        "VERSION_ANALYSIS": "lightrag_ext.us_dsl.version_retrieval_service:VersionRetrievalService",
        "IMPACT_ANALYSIS": "lightrag_ext.us_dsl.impact_analysis_eval:generate_impact_analysis_deterministic",
        "US_GENERATION": "lightrag_ext.us_dsl.us_generation_eval:US generation task specification only",
        "CODE_CONTEXT_HANDOFF": "future.code_context_adapter",
    }
    return targets.get(skill_id)


def _description(skill_id: str) -> str:
    if skill_id in FUTURE_LLM_SKILL_IDS:
        return "Records a future design/output task contract without generating final narrative content in 27A."
    if skill_id in ADAPTER_SKILL_IDS:
        return "Uses an existing deterministic or typed adapter contract and records capability evidence."
    if skill_id == "CODE_CONTEXT_HANDOFF":
        return "Represents a future code context handoff adapter; unavailable adapters must create capability gaps."
    return "Generic harness orchestration skill with no module-specific behavior."
