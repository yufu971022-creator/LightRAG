from __future__ import annotations

from lightrag_ext.us_dsl.harness_types import RequirementInput
from lightrag_ext.us_dsl.requirement_scenario_profile import build_requirement_scenario_profile
from lightrag_ext.us_dsl.requirement_scenario_router import route_requirement_scenario
from lightrag_ext.us_dsl.skill_capability_probe import probe_skill_capabilities
from lightrag_ext.us_dsl.skill_contracts import build_skill_contracts
from lightrag_ext.us_dsl.skill_dag_planner import build_harness_execution_plan


def req_zero(**overrides: object) -> RequirementInput:
    values = {
        "requirement_id": "T-ZERO",
        "requirement_text": "Add a previously unavailable coordination capability.",
        "source_document_refs": ["doc-zero"],
        "available_design_context": True,
        "metadata": {
            "primary_change_targets": ["new_capability"],
            "existing_feature_coverage": 0.1,
            "existing_semantic_object_coverage": 0.1,
            "existing_code_asset_coverage": 0.1,
            "novelty_score": 0.9,
            "new_business_object_ratio": 0.85,
            "evidence_sufficiency_score": 0.8,
            "profile_confidence": 0.8,
        },
    }
    values.update(overrides)
    return RequirementInput(**values)  # type: ignore[arg-type]


def req_many(**overrides: object) -> RequirementInput:
    values = {
        "requirement_id": "T-MANY",
        "requirement_text": "Change one existing state and assess broad downstream impacts.",
        "source_document_refs": ["doc-many"],
        "available_design_context": True,
        "metadata": {
            "primary_change_targets": ["state_value"],
            "existing_feature_coverage": 0.65,
            "existing_semantic_object_coverage": 0.75,
            "existing_code_asset_coverage": 0.4,
            "affected_feature_count": 4,
            "affected_domain_count": 2,
            "direct_impact_count": 3,
            "indirect_impact_count": 2,
            "graph_path_count": 3,
            "version_issue_count": 1,
            "evidence_sufficiency_score": 0.8,
            "profile_confidence": 0.8,
        },
    }
    values.update(overrides)
    return RequirementInput(**values)  # type: ignore[arg-type]


def req_local(**overrides: object) -> RequirementInput:
    values = {
        "requirement_id": "T-LOCAL",
        "requirement_text": "Adjust one field mapping for an existing interface.",
        "source_document_refs": ["doc-local"],
        "available_design_context": True,
        "available_code_context": False,
        "metadata": {
            "primary_change_targets": ["field_mapping"],
            "existing_feature_coverage": 0.86,
            "existing_semantic_object_coverage": 0.75,
            "existing_code_asset_coverage": 0.82,
            "affected_feature_count": 1,
            "affected_domain_count": 1,
            "direct_impact_count": 1,
            "indirect_impact_count": 0,
            "local_change_score": 0.88,
            "evidence_sufficiency_score": 0.8,
            "profile_confidence": 0.8,
        },
    }
    values.update(overrides)
    return RequirementInput(**values)  # type: ignore[arg-type]


def req_mixed() -> RequirementInput:
    return RequirementInput(
        requirement_id="T-MIXED",
        requirement_text="Add a new capability and modify several existing downstream capabilities.",
        source_document_refs=["doc-mixed"],
        available_design_context=True,
        metadata={
            "primary_change_targets": ["new_capability", "existing_state"],
            "existing_feature_coverage": 0.2,
            "existing_semantic_object_coverage": 0.55,
            "existing_code_asset_coverage": 0.2,
            "novelty_score": 0.86,
            "new_business_object_ratio": 0.72,
            "affected_feature_count": 4,
            "affected_domain_count": 2,
            "direct_impact_count": 3,
            "graph_path_count": 3,
            "evidence_sufficiency_score": 0.72,
            "profile_confidence": 0.7,
        },
    )


def req_insufficient() -> RequirementInput:
    return RequirementInput(
        requirement_id="T-INSUFFICIENT",
        requirement_text="Need a change, but no source evidence is available.",
        metadata={"evidence_sufficiency_score": 0.1, "profile_confidence": 0.2},
    )


def route_for(requirement: RequirementInput):
    profile = build_requirement_scenario_profile(requirement)
    return route_requirement_scenario(requirement, profile)


def plan_for(requirement: RequirementInput):
    contracts = build_skill_contracts()
    return build_harness_execution_plan(route_for(requirement), contracts=contracts, capability_matrix=probe_skill_capabilities(contracts))
