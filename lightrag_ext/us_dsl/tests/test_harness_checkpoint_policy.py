from __future__ import annotations

from lightrag_ext.us_dsl.harness_checkpoint_policy import evaluate_harness_checkpoints, required_checkpoint_types_for_scenario
from lightrag_ext.us_dsl.harness_context_assembler import assemble_harness_context
from lightrag_ext.us_dsl.requirement_scenario_profile import build_requirement_scenario_profile
from lightrag_ext.us_dsl.requirement_scenario_router import route_requirement_scenario
from lightrag_ext.us_dsl.tests.harness_27a_test_helpers import plan_for, req_insufficient, req_local, req_zero


def _context(req):
    profile = build_requirement_scenario_profile(req)
    route = route_requirement_scenario(req, profile)
    return assemble_harness_context(req, profile, route)


def test_zero_to_one_requires_assumption_checkpoint() -> None:
    assert "HUMAN_DECISION_REQUIRED" in required_checkpoint_types_for_scenario("ZERO_TO_ONE")
    results = evaluate_harness_checkpoints(_context(req_zero()), plan_for(req_zero()))
    assert any(item.checkpoint_type == "HUMAN_DECISION_REQUIRED" for item in results)


def test_one_to_many_requires_version_impact_evidence_checkpoints() -> None:
    checkpoints = required_checkpoint_types_for_scenario("ONE_TO_MANY")
    assert {"VERSION_CHECK", "IMPACT_BREADTH_CHECK", "EVIDENCE_CHECK"}.issubset(checkpoints)


def test_one_to_one_x_requires_code_context_checkpoint() -> None:
    checkpoints = required_checkpoint_types_for_scenario("ONE_TO_ONE_X")
    assert "CAPABILITY_CHECK" in checkpoints


def test_failed_checkpoint_blocks_downstream_completion() -> None:
    results = evaluate_harness_checkpoints(_context(req_local()), plan_for(req_local()))
    capability = next(item for item in results if item.checkpoint_type == "CAPABILITY_CHECK")
    assert capability.passed is False
    assert capability.blocks_downstream is True


def test_clarification_questions_are_structured() -> None:
    context = _context(req_insufficient())
    assert context.open_questions
    assert {"question_id", "question"}.issubset(context.open_questions[0])
