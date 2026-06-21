from __future__ import annotations

from lightrag_ext.us_dsl.harness_types import SkillPlanNode
from lightrag_ext.us_dsl.skill_dag_planner import detect_cycle, missing_required_dependencies
from lightrag_ext.us_dsl.tests.harness_27a_test_helpers import plan_for, req_local, req_many, req_zero


def test_dag_is_acyclic() -> None:
    assert detect_cycle(plan_for(req_many()).nodes) == []


def test_required_dependencies_exist() -> None:
    assert missing_required_dependencies(plan_for(req_zero()).nodes) == []


def test_unavailable_required_skill_blocks_or_creates_checkpoint() -> None:
    plan = plan_for(req_local())
    assert any(gap.skill_id == "CODE_CONTEXT_HANDOFF" and gap.blocks_plan for gap in plan.capability_gaps)
    assert "gap_code_context_handoff" in plan.manual_checkpoints


def test_optional_skill_can_skip_with_trace() -> None:
    plan = plan_for(req_zero())
    assert any(gap.skill_id == "UX_DESIGN_INPUT_PLANNING" and not gap.blocks_plan for gap in plan.optional_gaps)


def test_plan_hash_is_deterministic() -> None:
    assert plan_for(req_many()).plan_hash == plan_for(req_many()).plan_hash


def test_dag_has_no_module_specific_branch() -> None:
    plan = plan_for(req_many())
    forbidden = {"BANK", "FX"}
    assert all(not (set(node.skill_id.split("_")) & forbidden) for node in plan.nodes)


def test_required_dependency_detection_reports_missing_dependency() -> None:
    node = SkillPlanNode("n01_x", "X", ["MISSING"], True, "DRY_RUN", "AVAILABLE", {}, {}, False)
    assert missing_required_dependencies([node]) == [{"skill_id": "X", "missing_dependency": "MISSING"}]
