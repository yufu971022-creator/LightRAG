from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.harness_generalization_guard import scan_harness_runtime
from lightrag_ext.us_dsl.harness_types import RequirementInput
from lightrag_ext.us_dsl.requirement_scenario_router import route_requirement_scenario
from lightrag_ext.us_dsl.skill_registry import build_skill_registry


def test_holdout_module_uses_same_router_policy() -> None:
    req = RequirementInput(
        requirement_id="T-HOLDOUT-GEN",
        requirement_text="Unseen module requests broad impact assessment.",
        module_code="UNSEEN-MODULE-42",
        source_document_refs=["doc"],
        available_design_context=True,
        metadata={
            "primary_change_targets": ["state_change"],
            "existing_semantic_object_coverage": 0.7,
            "affected_feature_count": 4,
            "affected_domain_count": 2,
            "direct_impact_count": 3,
            "indirect_impact_count": 1,
            "graph_path_count": 2,
            "evidence_sufficiency_score": 0.8,
        },
    )
    route = route_requirement_scenario(req)
    assert route.selected_scenario == "ONE_TO_MANY"
    assert route.router_policy_version == "27A-router-v1"


def test_runtime_module_branch_count_is_zero() -> None:
    assert scan_harness_runtime(Path.cwd()).runtime_module_branch_count == 0


def test_entity_name_scenario_rule_count_is_zero() -> None:
    assert scan_harness_runtime(Path.cwd()).entity_name_scenario_rule_count == 0


def test_entity_name_skill_rule_count_is_zero() -> None:
    assert scan_harness_runtime(Path.cwd()).entity_name_skill_rule_count == 0


def test_new_module_requires_manifest_not_code_change() -> None:
    report = scan_harness_runtime(Path.cwd())
    assert report.new_module_requires_code_change is False
    assert build_skill_registry().module_specific_skill_count == 0
