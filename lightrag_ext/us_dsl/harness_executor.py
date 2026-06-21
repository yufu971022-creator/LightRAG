from __future__ import annotations

from .harness_checkpoint_policy import evaluate_harness_checkpoints, has_blocking_checkpoint
from .harness_context_assembler import assemble_harness_context
from .harness_state_machine import HarnessStateMachine
from .harness_types import HarnessRunResult, RequirementInput, SkillExecutionTrace
from .requirement_scenario_profile import build_requirement_scenario_profile
from .requirement_scenario_router import route_requirement_scenario
from .skill_capability_probe import probe_skill_capabilities
from .skill_contracts import build_skill_contracts
from .skill_dag_planner import build_harness_execution_plan

ALLOWED_EXECUTOR_MODES = {"PLAN_ONLY", "DRY_RUN", "DETERMINISTIC_EXECUTION"}


def run_harness(requirement: RequirementInput, *, mode: str = "PLAN_ONLY") -> HarnessRunResult:
    if mode not in ALLOWED_EXECUTOR_MODES:
        raise ValueError(f"unsupported 27A executor mode: {mode}")
    state = HarnessStateMachine()
    profile = build_requirement_scenario_profile(requirement)
    state.transition("PROFILED", event="profile_built", reason="scenario metrics computed")
    route = route_requirement_scenario(requirement, profile)
    state.transition("ROUTED", event="route_decided", reason=route.classification_status)
    context = assemble_harness_context(requirement, profile, route)

    if route.selected_scenario is None:
        state.transition("WAITING_FOR_CLARIFICATION", event="clarification_required", reason=route.classification_status)
        checkpoints = evaluate_harness_checkpoints(context, None)
        return HarnessRunResult(
            requirement_id=requirement.requirement_id,
            final_state=state.state,
            plan=None,
            context=context,
            checkpoint_results=checkpoints,
            execution_trace=[],
            state_transitions=list(state.transitions),
            capability_gaps=[],
        )

    state.transition("CONTEXT_READY", event="context_assembled", reason="context contract ready")
    contracts = build_skill_contracts()
    capability_matrix = probe_skill_capabilities(contracts)
    plan = build_harness_execution_plan(route, contracts=contracts, capability_matrix=capability_matrix)
    checkpoints = evaluate_harness_checkpoints(context, plan)
    if _insufficient_evidence_block(checkpoints):
        state.transition("CHECKPOINT_BLOCKED", event="checkpoint_failed", reason="insufficient evidence")
        state.transition("BLOCKED_BY_INSUFFICIENT_EVIDENCE", event="evidence_block", reason="evidence checkpoint failed")
        return HarnessRunResult(requirement.requirement_id, state.state, plan, context, checkpoints, [], list(state.transitions), plan.capability_gaps)
    if plan.blocking_gaps or has_blocking_checkpoint(checkpoints):
        state.transition("BLOCKED_BY_MISSING_CAPABILITY", event="capability_gap", reason="required capability unavailable")
        return HarnessRunResult(requirement.requirement_id, state.state, plan, context, checkpoints, [], list(state.transitions), plan.capability_gaps)

    state.transition("PLAN_READY", event="plan_built", reason="dag plan ready")
    if mode == "PLAN_ONLY":
        trace = [_planned_trace(node.node_id, node.skill_id, node.capability_status, node.execution_mode) for node in plan.nodes]
        return HarnessRunResult(requirement.requirement_id, state.state, plan, context, checkpoints, trace, list(state.transitions), plan.capability_gaps)

    state.transition("EXECUTING", event="dry_run_started", reason="27A dry run only")
    trace = [_dry_run_trace(node.node_id, node.skill_id, node.capability_status, node.execution_mode, node.required) for node in plan.nodes]
    if any(item.status == "BLOCKED_CAPABILITY_GAP" for item in trace):
        state.transition("BLOCKED_BY_MISSING_CAPABILITY", event="dry_run_blocked", reason="required capability missing")
    else:
        state.transition("DRY_RUN_COMPLETED", event="dry_run_completed", reason="no final output generated")
    return HarnessRunResult(requirement.requirement_id, state.state, plan, context, checkpoints, trace, list(state.transitions), plan.capability_gaps)


def _insufficient_evidence_block(checkpoints: list[object]) -> bool:
    return any(getattr(item, "checkpoint_type", None) == "EVIDENCE_CHECK" and not getattr(item, "passed", True) for item in checkpoints)


def _planned_trace(node_id: str, skill_id: str, status: str, mode: str) -> SkillExecutionTrace:
    return SkillExecutionTrace(
        node_id=node_id,
        skill_id=skill_id,
        status="PLANNED_ONLY",
        capability_status=status,  # type: ignore[arg-type]
        execution_mode=mode,  # type: ignore[arg-type]
        reason="27A plan-only mode does not execute business generation.",
        output={"final_output_generated": False},
    )


def _dry_run_trace(node_id: str, skill_id: str, status: str, mode: str, required: bool) -> SkillExecutionTrace:
    if mode in {"FUTURE_LLM_EXECUTION", "FUTURE_EXTERNAL_AGENT"}:
        if status in {"PLANNED_NOT_IMPLEMENTED", "BLOCKED_DEPENDENCY", "DISABLED"} and required:
            trace_status = "BLOCKED_CAPABILITY_GAP"
        elif status in {"PLANNED_NOT_IMPLEMENTED", "BLOCKED_DEPENDENCY", "DISABLED"}:
            trace_status = "SKIPPED_CAPABILITY_GAP"
        else:
            trace_status = "NOT_EXECUTED"
        return SkillExecutionTrace(
            node_id=node_id,
            skill_id=skill_id,
            status=trace_status,
            capability_status=status,  # type: ignore[arg-type]
            execution_mode=mode,  # type: ignore[arg-type]
            reason="Future LLM or external-agent skill is not executed in 27A.",
            output={"future_execution_contract": True, "final_business_text_generated": False},
        )
    if status in {"PLANNED_NOT_IMPLEMENTED", "BLOCKED_DEPENDENCY", "DISABLED"}:
        return SkillExecutionTrace(
            node_id=node_id,
            skill_id=skill_id,
            status="BLOCKED_CAPABILITY_GAP" if required else "SKIPPED_CAPABILITY_GAP",
            capability_status=status,  # type: ignore[arg-type]
            execution_mode=mode,  # type: ignore[arg-type]
            reason="Capability unavailable; recorded gap instead of fake output.",
            output={"capability_gap_visible": True},
        )
    return SkillExecutionTrace(
        node_id=node_id,
        skill_id=skill_id,
        status="DRY_RUN_COMPLETED",
        capability_status=status,  # type: ignore[arg-type]
        execution_mode=mode,  # type: ignore[arg-type]
        reason="Deterministic offline skill contract checked without side effects.",
        output={"contract_checked": True, "final_output_generated": False},
    )
