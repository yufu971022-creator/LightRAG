from __future__ import annotations

from lightrag_ext.us_dsl.harness_executor import run_harness
from lightrag_ext.us_dsl.tests.harness_27a_test_helpers import req_insufficient, req_local, req_many, req_zero


def test_plan_only_ends_at_plan_ready() -> None:
    result = run_harness(req_many(), mode="PLAN_ONLY")
    assert result.final_state == "PLAN_READY"
    assert result.final_us_generated is False


def test_dry_run_never_marks_final_output_approved() -> None:
    result = run_harness(req_many(), mode="DRY_RUN")
    assert result.final_state == "DRY_RUN_COMPLETED"
    assert result.final_us_generated is False
    assert result.final_solution_document_generated is False


def test_missing_capability_is_visible() -> None:
    result = run_harness(req_local(), mode="DRY_RUN")
    assert result.final_state == "BLOCKED_BY_MISSING_CAPABILITY"
    assert any(gap.skill_id == "CODE_CONTEXT_HANDOFF" for gap in result.capability_gaps)


def test_insufficient_evidence_is_visible() -> None:
    result = run_harness(req_insufficient(), mode="PLAN_ONLY")
    assert result.final_state == "WAITING_FOR_CLARIFICATION"
    assert result.context is not None
    assert result.context.scenario_route.classification_status == "INSUFFICIENT_EVIDENCE"


def test_execution_trace_is_complete() -> None:
    result = run_harness(req_many(), mode="DRY_RUN")
    assert result.plan is not None
    assert len(result.execution_trace) == len(result.plan.nodes)


def test_no_fake_output_for_future_llm_skill() -> None:
    result = run_harness(req_zero(), mode="PLAN_ONLY")
    assert any(item.execution_mode == "FUTURE_LLM_EXECUTION" for item in result.execution_trace)
    assert all(item.output.get("final_output_generated") is False for item in result.execution_trace)
