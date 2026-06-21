from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .harness_types import RequirementScenario, to_plain_dict


@dataclass(frozen=True)
class ScenarioSkillTemplate:
    scenario: RequirementScenario
    skill_order: list[str]
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    optional_skill_ids: list[str] = field(default_factory=list)
    policy_version: str = "27A-template-v1"

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


def build_scenario_skill_templates() -> dict[RequirementScenario, ScenarioSkillTemplate]:
    return {
        "ZERO_TO_ONE": _template(
            "ZERO_TO_ONE",
            [
                "REQUIREMENT_INTAKE",
                "SCENARIO_CLASSIFICATION",
                "TRUSTED_KNOWLEDGE_RETRIEVAL",
                "NOVELTY_GAP_ANALYSIS",
                "CLARIFICATION_QUESTION_GENERATION",
                "FEATURE_DECOMPOSITION",
                "FUNCTION_DECOMPOSITION",
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
                "CROSS_OUTPUT_CONSISTENCY_CHECK",
                "FINAL_QUALITY_GATE",
            ],
            optional={"UX_DESIGN_INPUT_PLANNING"},
        ),
        "ONE_TO_MANY": _template(
            "ONE_TO_MANY",
            [
                "REQUIREMENT_INTAKE",
                "SCENARIO_CLASSIFICATION",
                "TRUSTED_KNOWLEDGE_RETRIEVAL",
                "VERSION_ANALYSIS",
                "CURRENT_STATE_ANALYSIS",
                "PRIMARY_CHANGE_TARGET_IDENTIFICATION",
                "IMPACT_ANALYSIS",
                "CLARIFICATION_QUESTION_GENERATION",
                "FEATURE_DECOMPOSITION",
                "FUNCTION_DECOMPOSITION",
                "HIGH_LEVEL_SOLUTION_PLANNING",
                "DETAILED_DESIGN_PLANNING",
                "FIELD_SPEC_PLANNING",
                "PROCESS_STATE_DESIGN_PLANNING",
                "INTEGRATION_DESIGN_PLANNING",
                "PERMISSION_AUDIT_DESIGN_PLANNING",
                "MIGRATION_INITIALIZATION_PLANNING",
                "DFX_DESIGN_PLANNING",
                "UX_DESIGN_INPUT_PLANNING",
                "US_GENERATION",
                "AC_GENERATION",
                "TEST_SCOPE_PLANNING",
                "CROSS_OUTPUT_CONSISTENCY_CHECK",
                "FINAL_QUALITY_GATE",
            ],
            optional={"UX_DESIGN_INPUT_PLANNING"},
        ),
        "ONE_TO_ONE_X": _template(
            "ONE_TO_ONE_X",
            [
                "REQUIREMENT_INTAKE",
                "SCENARIO_CLASSIFICATION",
                "TRUSTED_KNOWLEDGE_RETRIEVAL",
                "VERSION_ANALYSIS",
                "CURRENT_STATE_ANALYSIS",
                "PRIMARY_CHANGE_TARGET_IDENTIFICATION",
                "LOCAL_IMPACT_CHECK",
                "CODE_CONTEXT_HANDOFF",
                "DETAILED_DESIGN_PLANNING",
                "FIELD_SPEC_PLANNING",
                "INTEGRATION_DESIGN_PLANNING",
                "PROCESS_STATE_DESIGN_PLANNING",
                "DFX_DESIGN_PLANNING",
                "US_GENERATION",
                "AC_GENERATION",
                "TEST_SCOPE_PLANNING",
                "CROSS_OUTPUT_CONSISTENCY_CHECK",
                "FINAL_QUALITY_GATE",
            ],
            optional=set(),
        ),
    }


def _template(scenario: RequirementScenario, skill_order: list[str], optional: set[str]) -> ScenarioSkillTemplate:
    dependencies: dict[str, list[str]] = {}
    previous: str | None = None
    for skill_id in skill_order:
        dependencies[skill_id] = [previous] if previous else []
        previous = skill_id
    return ScenarioSkillTemplate(
        scenario=scenario,
        skill_order=skill_order,
        dependencies=dependencies,
        optional_skill_ids=sorted(optional),
    )
