from __future__ import annotations

from lightrag_ext.us_dsl.scenario_skill_templates import build_scenario_skill_templates


def test_zero_to_one_plan_contains_novelty_and_decomposition() -> None:
    template = build_scenario_skill_templates()["ZERO_TO_ONE"]
    assert "NOVELTY_GAP_ANALYSIS" in template.skill_order
    assert "FEATURE_DECOMPOSITION" in template.skill_order
    assert "FUNCTION_DECOMPOSITION" in template.skill_order


def test_one_to_many_plan_contains_version_and_impact() -> None:
    template = build_scenario_skill_templates()["ONE_TO_MANY"]
    assert "VERSION_ANALYSIS" in template.skill_order
    assert "IMPACT_ANALYSIS" in template.skill_order
    assert "TEST_SCOPE_PLANNING" in template.skill_order


def test_one_to_one_x_plan_contains_local_scope_and_code_handoff() -> None:
    template = build_scenario_skill_templates()["ONE_TO_ONE_X"]
    assert "LOCAL_IMPACT_CHECK" in template.skill_order
    assert "CODE_CONTEXT_HANDOFF" in template.skill_order
