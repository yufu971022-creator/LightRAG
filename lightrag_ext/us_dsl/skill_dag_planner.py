from __future__ import annotations

import hashlib
import json
from typing import Any

from .harness_types import CapabilityGap, HarnessExecutionPlan, ScenarioRouteDecision, SkillPlanNode
from .scenario_skill_templates import ScenarioSkillTemplate, build_scenario_skill_templates
from .skill_capability_probe import SkillCapabilityEvidence, probe_skill_capabilities
from .skill_contracts import FUTURE_LLM_SKILL_IDS, build_skill_contracts


def build_harness_execution_plan(
    route: ScenarioRouteDecision,
    *,
    contracts: dict[str, Any] | None = None,
    capability_matrix: dict[str, SkillCapabilityEvidence] | None = None,
    templates: dict[str, ScenarioSkillTemplate] | None = None,
) -> HarnessExecutionPlan:
    if route.selected_scenario is None:
        raise ValueError("cannot build execution plan without a selected scenario")
    contracts = contracts or build_skill_contracts()
    capability_matrix = capability_matrix or probe_skill_capabilities(contracts)
    templates = templates or build_scenario_skill_templates()
    template = templates[route.selected_scenario]
    _validate_template(template, contracts)

    nodes: list[SkillPlanNode] = []
    gaps: list[CapabilityGap] = []
    for index, skill_id in enumerate(template.skill_order, start=1):
        contract = contracts[skill_id]
        evidence = capability_matrix[skill_id]
        required = skill_id not in set(template.optional_skill_ids)
        status = evidence.probed_status
        node = SkillPlanNode(
            node_id=f"n{index:02d}_{skill_id.lower()}",
            skill_id=skill_id,
            dependencies=list(template.dependencies.get(skill_id, [])),
            required=required,
            execution_mode=_execution_mode(skill_id, status),
            capability_status=status,  # type: ignore[arg-type]
            input_bindings={name: f"context.{name}" for name in contract.required_inputs},
            expected_output_schema=dict(contract.output_schema),
            checkpoint_after=contract.checkpoint_after,
            skip_condition=None if required else "skip_when_capability_unavailable",
            block_condition="missing_required_capability" if required and _unavailable(status) else None,
            fallback_skill_ids=["CLARIFICATION_QUESTION_GENERATION"] if required and _unavailable(status) else [],
        )
        nodes.append(node)
        if _unavailable(status):
            gaps.append(_gap(skill_id, status, required))

    edges = _edges(nodes)
    order = [node.node_id for node in nodes]
    blocking = [gap for gap in gaps if gap.blocks_plan]
    optional = [gap for gap in gaps if not gap.blocks_plan]
    required_context = sorted({binding for node in nodes for binding in node.input_bindings.values()})
    manual_checkpoints = _manual_checkpoints(route.selected_scenario, gaps)
    plan_hash = _plan_hash(route, nodes, manual_checkpoints)
    return HarnessExecutionPlan(
        plan_id=f"plan_{route.requirement_id}_{route.selected_scenario.lower()}",
        requirement_id=route.requirement_id,
        scenario_route=route,
        nodes=nodes,
        edges=edges,
        topological_order=order,
        required_context=required_context,
        capability_gaps=gaps,
        blocking_gaps=blocking,
        optional_gaps=optional,
        manual_checkpoints=manual_checkpoints,
        estimated_steps=len(nodes),
        plan_hash=plan_hash,
    )


def detect_cycle(nodes: list[SkillPlanNode]) -> list[list[str]]:
    node_ids = {node.skill_id for node in nodes}
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[list[str]] = []
    deps = {node.skill_id: list(node.dependencies) for node in nodes}

    def walk(skill_id: str, path: list[str]) -> None:
        if skill_id in visiting:
            cycles.append([*path, skill_id])
            return
        if skill_id in visited:
            return
        visiting.add(skill_id)
        for dep in deps.get(skill_id, []):
            if dep in node_ids:
                walk(dep, [*path, skill_id])
        visiting.remove(skill_id)
        visited.add(skill_id)

    for node in nodes:
        walk(node.skill_id, [])
    return cycles


def missing_required_dependencies(nodes: list[SkillPlanNode]) -> list[dict[str, str]]:
    existing = {node.skill_id for node in nodes}
    missing: list[dict[str, str]] = []
    for node in nodes:
        for dep in node.dependencies:
            if dep not in existing:
                missing.append({"skill_id": node.skill_id, "missing_dependency": dep})
    return missing


def _validate_template(template: ScenarioSkillTemplate, contracts: dict[str, Any]) -> None:
    unregistered = [skill_id for skill_id in template.skill_order if skill_id not in contracts]
    if unregistered:
        raise ValueError(f"template uses unregistered skills: {unregistered}")
    missing = [dep for deps in template.dependencies.values() for dep in deps if dep and dep not in template.skill_order]
    if missing:
        raise ValueError(f"template has missing dependencies: {sorted(set(missing))}")


def _edges(nodes: list[SkillPlanNode]) -> list[tuple[str, str]]:
    by_skill = {node.skill_id: node.node_id for node in nodes}
    return [(by_skill[dep], node.node_id) for node in nodes for dep in node.dependencies if dep in by_skill]


def _execution_mode(skill_id: str, status: str) -> str:
    if skill_id == "CODE_CONTEXT_HANDOFF":
        return "FUTURE_EXTERNAL_AGENT"
    if skill_id in FUTURE_LLM_SKILL_IDS:
        return "FUTURE_LLM_EXECUTION"
    if status == "ADAPTER_AVAILABLE":
        return "DETERMINISTIC_EXECUTION"
    return "DRY_RUN"


def _unavailable(status: str) -> bool:
    return status in {"PLANNED_NOT_IMPLEMENTED", "BLOCKED_DEPENDENCY", "DISABLED"}


def _gap(skill_id: str, status: str, required: bool) -> CapabilityGap:
    return CapabilityGap(
        gap_id=f"gap_{skill_id.lower()}",
        skill_id=skill_id,
        gap_type=status,
        severity="HIGH" if required else "MEDIUM",
        required_for_completion=required,
        missing_dependency="implemented_adapter_or_runtime_capability",
        available_fallback="manual_checkpoint" if required else "skip_with_trace",
        manual_action="Provide capability implementation or explicitly accept reduced scope.",
        blocks_plan=required,
    )


def _manual_checkpoints(scenario: str, gaps: list[CapabilityGap]) -> list[str]:
    checkpoints = {
        "ZERO_TO_ONE": ["assumption_clarification_checkpoint"],
        "ONE_TO_MANY": ["version_impact_evidence_checkpoint"],
        "ONE_TO_ONE_X": ["local_scope_and_code_context_checkpoint"],
    }[scenario]
    return [*checkpoints, *[gap.gap_id for gap in gaps if gap.required_for_completion]]


def _plan_hash(route: ScenarioRouteDecision, nodes: list[SkillPlanNode], manual_checkpoints: list[str]) -> str:
    payload = {
        "requirement_id": route.requirement_id,
        "scenario": route.selected_scenario,
        "router_policy_version": route.router_policy_version,
        "nodes": [
            {
                "skill_id": node.skill_id,
                "dependencies": node.dependencies,
                "required": node.required,
                "capability_status": node.capability_status,
                "execution_mode": node.execution_mode,
            }
            for node in nodes
        ],
        "manual_checkpoints": manual_checkpoints,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
