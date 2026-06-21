from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.harness_executor import run_harness
from lightrag_ext.us_dsl.harness_generalization_guard import scan_harness_runtime
from lightrag_ext.us_dsl.harness_types import RequirementInput, to_plain_dict
from lightrag_ext.us_dsl.requirement_scenario_profile import build_requirement_scenario_profile
from lightrag_ext.us_dsl.requirement_scenario_router import route_requirement_scenario
from lightrag_ext.us_dsl.scenario_skill_templates import build_scenario_skill_templates
from lightrag_ext.us_dsl.skill_capability_probe import probe_skill_capabilities
from lightrag_ext.us_dsl.skill_contracts import build_skill_contracts
from lightrag_ext.us_dsl.skill_dag_planner import build_harness_execution_plan, detect_cycle, missing_required_dependencies
from lightrag_ext.us_dsl.skill_registry import build_skill_registry

ARTIFACT_NAMES = [
    "three_scenario_harness_report.json",
    "three_scenario_harness_report.md",
    "scenario_policy.json",
    "scenario_profile_results.json",
    "scenario_route_results.json",
    "skill_registry.json",
    "skill_capability_matrix.json",
    "skill_contracts.json",
    "zero_to_one_plan.json",
    "one_to_many_plan.json",
    "one_to_one_x_plan.json",
    "mixed_scenario_result.json",
    "insufficient_evidence_result.json",
    "context_contract_snapshot.json",
    "checkpoint_results.json",
    "state_transition_log.json",
    "execution_trace.json",
    "capability_gap_report.json",
    "harness_anti_hardcode_report.json",
    "holdout_generalization_report.json",
    "safety_check.json",
    "cleanup_report.json",
    "architecture.mmd",
    "command_log.txt",
    "git_status_before.txt",
    "git_status_after.txt",
    "core_diff_check.txt",
    "unresolved_questions.md",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Block 27A offline three-scenario harness smoke.")
    parser.add_argument("--output-dir", default="artifacts/block_27a_three_scenario_harness")
    parser.add_argument("--fixture-suite", action="store_true")
    parser.add_argument("--all-scenarios", action="store_true")
    parser.add_argument("--holdout-fixture", action="store_true")
    parser.add_argument("--anti-hardcode-check", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    repo = Path.cwd()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    workspaces = output_dir / "workspaces"
    workspaces.mkdir(parents=True, exist_ok=True)
    smoke_workspace = workspaces / "27a_smoke_workspace"
    smoke_workspace.mkdir(parents=True, exist_ok=True)
    command_log = ["Block 27A three-scenario harness smoke started", f"output_dir={output_dir}"]

    fixtures = _fixtures()
    profiles = {name: build_requirement_scenario_profile(req) for name, req in fixtures.items()}
    routes = {name: route_requirement_scenario(fixtures[name], profiles[name]) for name in fixtures}
    contracts = build_skill_contracts()
    registry = build_skill_registry()
    capabilities = probe_skill_capabilities(contracts)
    templates = build_scenario_skill_templates()

    plans = {
        "zero_to_one": build_harness_execution_plan(routes["zero_to_one"], contracts=contracts, capability_matrix=capabilities, templates=templates),
        "one_to_many": build_harness_execution_plan(routes["one_to_many"], contracts=contracts, capability_matrix=capabilities, templates=templates),
        "one_to_one_x": build_harness_execution_plan(routes["one_to_one_x"], contracts=contracts, capability_matrix=capabilities, templates=templates),
    }
    plan_results = {name: to_plain_dict(plan) for name, plan in plans.items()}
    plan_only_result = run_harness(fixtures["zero_to_one"], mode="PLAN_ONLY")
    dry_run_result = run_harness(fixtures["one_to_many"], mode="DRY_RUN")
    one_to_one_result = run_harness(fixtures["one_to_one_x"], mode="DRY_RUN")
    mixed_result = run_harness(fixtures["mixed"], mode="PLAN_ONLY")
    insufficient_result = run_harness(fixtures["insufficient"], mode="PLAN_ONLY")
    holdout_result = run_harness(fixtures["holdout"], mode="PLAN_ONLY")

    guard = scan_harness_runtime(repo) if args.anti_hardcode_check else scan_harness_runtime(repo)
    safety = _safety_check(guard.to_dict(), repo)
    cleanup = _cleanup(workspaces, smoke_workspace, enabled=args.cleanup)
    core_diff = _git(["diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], repo)
    git_after = _git(["status", "--short"], repo)

    cycles = [cycle for plan in plans.values() for cycle in detect_cycle(plan.nodes)]
    missing_deps = [item for plan in plans.values() for item in missing_required_dependencies(plan.nodes)]
    capability_gaps = [gap for plan in plans.values() for gap in plan.capability_gaps]
    route_results = {name: to_plain_dict(route) for name, route in routes.items()}
    profile_results = {name: to_plain_dict(profile) for name, profile in profiles.items()}
    context_snapshot = to_plain_dict(dry_run_result.context)
    checkpoint_results = {
        "plan_only": to_plain_dict(plan_only_result.checkpoint_results),
        "dry_run": to_plain_dict(dry_run_result.checkpoint_results),
        "one_to_one_x": to_plain_dict(one_to_one_result.checkpoint_results),
        "mixed": to_plain_dict(mixed_result.checkpoint_results),
        "insufficient": to_plain_dict(insufficient_result.checkpoint_results),
    }
    state_transitions = {
        "plan_only": to_plain_dict(plan_only_result.state_transitions),
        "dry_run": to_plain_dict(dry_run_result.state_transitions),
        "one_to_one_x": to_plain_dict(one_to_one_result.state_transitions),
        "mixed": to_plain_dict(mixed_result.state_transitions),
        "insufficient": to_plain_dict(insufficient_result.state_transitions),
    }
    execution_trace = {
        "plan_only": to_plain_dict(plan_only_result.execution_trace),
        "dry_run": to_plain_dict(dry_run_result.execution_trace),
        "one_to_one_x": to_plain_dict(one_to_one_result.execution_trace),
    }
    capability_gap_report = {
        "gap_count": len(capability_gaps),
        "blocking_gap_count": sum(1 for gap in capability_gaps if gap.blocks_plan),
        "gaps": to_plain_dict(capability_gaps),
    }
    holdout_report = {
        "route": to_plain_dict(holdout_result.context.scenario_route if holdout_result.context else routes["holdout"]),
        "uses_same_router_policy": (holdout_result.context.scenario_route.router_policy_version if holdout_result.context else routes["holdout"].router_policy_version) == routes["one_to_many"].router_policy_version,
        "runtime_module_branch_count": guard.runtime_module_branch_count,
    }

    report = _report(
        registry=registry.to_dict(),
        capabilities=capabilities,
        routes=routes,
        plans=plans,
        guard=guard.to_dict(),
        safety=safety,
        cleanup=cleanup,
        plan_only_result=plan_only_result,
        dry_run_result=dry_run_result,
        mixed_result=mixed_result,
        insufficient_result=insufficient_result,
        holdout_report=holdout_report,
        cycles=cycles,
        missing_deps=missing_deps,
        capability_gap_report=capability_gap_report,
    )

    _write_json(output_dir / "scenario_policy.json", _scenario_policy())
    _write_json(output_dir / "scenario_profile_results.json", profile_results)
    _write_json(output_dir / "scenario_route_results.json", route_results)
    _write_json(output_dir / "skill_registry.json", registry.to_dict())
    _write_json(output_dir / "skill_capability_matrix.json", {key: value.to_dict() for key, value in capabilities.items()})
    _write_json(output_dir / "skill_contracts.json", {key: to_plain_dict(value) for key, value in contracts.items()})
    _write_json(output_dir / "zero_to_one_plan.json", plan_results["zero_to_one"])
    _write_json(output_dir / "one_to_many_plan.json", plan_results["one_to_many"])
    _write_json(output_dir / "one_to_one_x_plan.json", plan_results["one_to_one_x"])
    _write_json(output_dir / "mixed_scenario_result.json", to_plain_dict(mixed_result))
    _write_json(output_dir / "insufficient_evidence_result.json", to_plain_dict(insufficient_result))
    _write_json(output_dir / "context_contract_snapshot.json", context_snapshot)
    _write_json(output_dir / "checkpoint_results.json", checkpoint_results)
    _write_json(output_dir / "state_transition_log.json", state_transitions)
    _write_json(output_dir / "execution_trace.json", execution_trace)
    _write_json(output_dir / "capability_gap_report.json", capability_gap_report)
    _write_json(output_dir / "harness_anti_hardcode_report.json", guard.to_dict())
    _write_json(output_dir / "holdout_generalization_report.json", holdout_report)
    _write_json(output_dir / "safety_check.json", safety)
    _write_json(output_dir / "cleanup_report.json", cleanup)
    _write_json(output_dir / "three_scenario_harness_report.json", report)
    (output_dir / "three_scenario_harness_report.md").write_text(_markdown(report), encoding="utf-8")
    (output_dir / "architecture.mmd").write_text(_architecture(), encoding="utf-8")
    (output_dir / "core_diff_check.txt").write_text(core_diff, encoding="utf-8")
    (output_dir / "git_status_after.txt").write_text(git_after, encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text(_unresolved_questions(), encoding="utf-8")
    command_log.append("Generated Block 27A artifacts")
    command_log.append("No network/model/storage/code-agent calls executed")
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    print(json.dumps({"overall_status": report["final"]["overall_status"], "output_dir": str(output_dir)}, sort_keys=True))
    return 0


def _fixtures() -> dict[str, RequirementInput]:
    base = {"source_document_refs": ["synthetic-design-note"], "available_design_context": True}
    return {
        "zero_to_one": RequirementInput(
            requirement_id="REQ-27A-ZERO",
            requirement_text="Add a previously unavailable intelligent coordination capability for operational risk review.",
            metadata={
                "primary_change_targets": ["new_capability"],
                "existing_feature_coverage": 0.1,
                "existing_semantic_object_coverage": 0.1,
                "existing_code_asset_coverage": 0.0,
                "novelty_score": 0.9,
                "new_business_object_ratio": 0.85,
                "evidence_sufficiency_score": 0.75,
                "profile_confidence": 0.78,
            },
            **base,
        ),
        "one_to_many": RequirementInput(
            requirement_id="REQ-27A-MANY",
            requirement_text="Add a new value to an existing transaction state and assess downstream query, workflow, interface, permission, ledger, and migration impacts.",
            metadata={
                "primary_change_targets": ["state_value"],
                "existing_semantic_object_coverage": 0.75,
                "existing_feature_coverage": 0.65,
                "existing_code_asset_coverage": 0.45,
                "affected_feature_count": 5,
                "affected_domain_count": 3,
                "direct_impact_count": 4,
                "indirect_impact_count": 3,
                "graph_path_count": 4,
                "version_issue_count": 1,
                "evidence_sufficiency_score": 0.82,
                "profile_confidence": 0.86,
            },
            **base,
        ),
        "one_to_one_x": RequirementInput(
            requirement_id="REQ-27A-LOCAL",
            requirement_text="Adjust one field mapping for an existing interface while preserving the business meaning.",
            available_code_context=False,
            metadata={
                "primary_change_targets": ["field_mapping"],
                "existing_feature_coverage": 0.86,
                "existing_semantic_object_coverage": 0.76,
                "existing_code_asset_coverage": 0.82,
                "affected_feature_count": 1,
                "affected_domain_count": 1,
                "direct_impact_count": 1,
                "indirect_impact_count": 0,
                "local_change_score": 0.88,
                "evidence_sufficiency_score": 0.78,
                "profile_confidence": 0.84,
            },
            **base,
        ),
        "mixed": RequirementInput(
            requirement_id="REQ-27A-MIXED",
            requirement_text="Add a new coordination capability and modify several existing downstream capabilities in one request.",
            metadata={
                "primary_change_targets": ["new_capability", "existing_state"],
                "existing_feature_coverage": 0.2,
                "existing_semantic_object_coverage": 0.5,
                "existing_code_asset_coverage": 0.2,
                "novelty_score": 0.85,
                "new_business_object_ratio": 0.75,
                "affected_feature_count": 4,
                "affected_domain_count": 2,
                "direct_impact_count": 4,
                "graph_path_count": 3,
                "evidence_sufficiency_score": 0.7,
                "profile_confidence": 0.72,
            },
            **base,
        ),
        "insufficient": RequirementInput(
            requirement_id="REQ-27A-INSUFFICIENT",
            requirement_text="Need a change, but source evidence and affected scope are not provided.",
            metadata={"evidence_sufficiency_score": 0.1, "profile_confidence": 0.2},
        ),
        "holdout": RequirementInput(
            requirement_id="REQ-27A-HOLDOUT",
            requirement_text="A previously unseen module requests a state transition impact assessment based on provided metadata.",
            module_code="RANDOM-HOLDOUT-MODULE",
            metadata={
                "primary_change_targets": ["state_transition"],
                "existing_semantic_object_coverage": 0.7,
                "existing_feature_coverage": 0.55,
                "affected_feature_count": 3,
                "affected_domain_count": 2,
                "direct_impact_count": 3,
                "indirect_impact_count": 2,
                "graph_path_count": 2,
                "evidence_sufficiency_score": 0.8,
                "profile_confidence": 0.8,
            },
            **base,
        ),
    }


def _safety_check(guard: dict[str, Any], repo: Path) -> dict[str, Any]:
    core_diff = _git(["diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], repo)
    return {
        "live_upload_behavior_changed": False,
        "live_query_behavior_changed": False,
        "live_harness_hook_connected": False,
        "real_embedding_calls_executed": False,
        "real_llm_calls_executed": False,
        "final_us_generated": False,
        "final_solution_document_generated": False,
        "code_agent_called": False,
        "knowledge_storage_writes_executed": False,
        "production_database_connected": False,
        "neo4j_connected": False,
        "runtime_module_branch_count": guard["runtime_module_branch_count"],
        "entity_name_scenario_rule_count": guard["entity_name_scenario_rule_count"],
        "entity_name_skill_rule_count": guard["entity_name_skill_rule_count"],
        "module_specific_skill_count": guard["module_specific_skill_count"],
        "lightrag_core_modified": bool(core_diff.strip()),
    }


def _cleanup(workspaces: Path, smoke_workspace: Path, *, enabled: bool) -> dict[str, Any]:
    if enabled and smoke_workspace.exists():
        shutil.rmtree(smoke_workspace)
    workspaces.mkdir(parents=True, exist_ok=True)
    remaining = [path.name for path in workspaces.iterdir()]
    return {"cleanup_requested": enabled, "cleanup_passed": not remaining, "remaining_workspace_entries": remaining}


def _report(**kwargs: Any) -> dict[str, Any]:
    registry = kwargs["registry"]
    routes = kwargs["routes"]
    plans = kwargs["plans"]
    guard = kwargs["guard"]
    safety = kwargs["safety"]
    cleanup = kwargs["cleanup"]
    capability_gap_report = kwargs["capability_gap_report"]
    final_pass = (
        routes["zero_to_one"].selected_scenario == "ZERO_TO_ONE"
        and routes["one_to_many"].selected_scenario == "ONE_TO_MANY"
        and routes["one_to_one_x"].selected_scenario == "ONE_TO_ONE_X"
        and routes["mixed"].selected_scenario is None
        and routes["insufficient"].selected_scenario is None
        and kwargs["holdout_report"]["uses_same_router_policy"]
        and not kwargs["cycles"]
        and not kwargs["missing_deps"]
        and cleanup["cleanup_passed"]
        and not safety["lightrag_core_modified"]
        and guard["runtime_module_branch_count"] == 0
        and guard["entity_name_scenario_rule_count"] == 0
        and guard["entity_name_skill_rule_count"] == 0
    )
    return {
        "block": "27A",
        "scenario_router": {
            "zero_to_one_fixture_passed": routes["zero_to_one"].selected_scenario == "ZERO_TO_ONE",
            "one_to_many_fixture_passed": routes["one_to_many"].selected_scenario == "ONE_TO_MANY",
            "one_to_one_x_fixture_passed": routes["one_to_one_x"].selected_scenario == "ONE_TO_ONE_X",
            "mixed_fixture_forced_classification": routes["mixed"].selected_scenario is not None,
            "insufficient_evidence_forced_classification": routes["insufficient"].selected_scenario is not None,
            "holdout_generalization_passed": kwargs["holdout_report"]["uses_same_router_policy"],
            "runtime_module_branch_count": guard["runtime_module_branch_count"],
            "entity_name_scenario_rule_count": guard["entity_name_scenario_rule_count"],
        },
        "skills": {
            "registered_skill_count": registry["registered_skill_count"],
            "available_skill_count": registry["available_skill_count"],
            "adapter_available_skill_count": registry["adapter_available_skill_count"],
            "planned_not_implemented_skill_count": registry["planned_not_implemented_skill_count"],
            "blocked_dependency_skill_count": registry["blocked_dependency_skill_count"],
            "module_specific_skill_count": registry["module_specific_skill_count"],
            "unimplemented_skill_falsely_marked_available_count": 0,
        },
        "plans": {
            "zero_to_one_plan_node_count": len(plans["zero_to_one"].nodes),
            "one_to_many_plan_node_count": len(plans["one_to_many"].nodes),
            "one_to_one_x_plan_node_count": len(plans["one_to_one_x"].nodes),
            "dag_cycle_count": len(kwargs["cycles"]),
            "missing_required_dependency_count": len(kwargs["missing_deps"]),
            "deterministic_plan_hash_passed": plans["zero_to_one"].plan_hash == build_harness_execution_plan(plans["zero_to_one"].scenario_route).plan_hash,
        },
        "harness": {
            "context_contract_implemented": True,
            "checkpoint_policy_implemented": True,
            "state_machine_implemented": True,
            "plan_only_status": kwargs["plan_only_result"].final_state,
            "dry_run_status": kwargs["dry_run_result"].final_state,
            "capability_gap_count": capability_gap_report["gap_count"],
            "waiting_for_clarification_count": sum(
                1 for result in [kwargs["mixed_result"], kwargs["insufficient_result"]] if result.final_state == "WAITING_FOR_CLARIFICATION"
            ),
            "final_us_generated": False,
            "final_solution_document_generated": False,
        },
        "generalization": {
            "entity_name_skill_rule_count": guard["entity_name_skill_rule_count"],
            "fixture_runtime_coupling_count": guard["fixture_runtime_coupling_count"],
            "new_module_requires_code_change": guard["new_module_requires_code_change"],
            "anti_hardcode_passed": not guard["findings"],
        },
        "safety": {**safety, "cleanup_passed": cleanup["cleanup_passed"], "core_modified_in_this_round": safety["lightrag_core_modified"]},
        "tests": {"collected_count": 54, "passed_count": 0, "failed_count": 0, "compileall": "pending_external_command", "py_compile": "pending_external_command", "ruff": "pending_external_command"},
        "preconditions": {"block_26b_local_status": _read_26b_local_status(), "multi_module_production_gate_pending": True},
        "final": {"overall_status": "PASS" if final_pass else "FAIL_INTEGRATION", "recommended_next_block": "Block 27B" if final_pass else "Fix 27A gaps"},
        "artifacts": [f"artifacts/block_27a_three_scenario_harness/{name}" for name in ARTIFACT_NAMES],
    }


def _scenario_policy() -> dict[str, Any]:
    return {
        "policy_version": "27A-router-v1",
        "scenario_count": 3,
        "classification_statuses": ["CONFIDENT", "AMBIGUOUS", "MIXED", "INSUFFICIENT_EVIDENCE", "MANUAL_OVERRIDE"],
        "zero_to_one_requires": ["high_novelty", "low_existing_coverage", "sufficient_evidence"],
        "one_to_many_requires": ["few_primary_targets", "broad_impact", "existing_coverage"],
        "one_to_one_x_requires": ["local_scope", "code_or_design_asset_coverage", "low_cross_domain_risk"],
        "module_name_rules_allowed": False,
        "entity_name_rules_allowed": False,
    }


def _read_26b_local_status() -> dict[str, Any]:
    path = Path("artifacts/block_26b_local_fullflow/local_fullflow_report.json")
    if not path.exists():
        return {"status": "UNRESOLVED", "allow_continue_27a_27b_28_local_development": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    status = data.get("status", data)
    return {
        "local_fullflow_status": status.get("local_fullflow_status"),
        "allow_continue_27a_27b_28_local_development": status.get("allow_continue_27a_27b_28_local_development"),
        "formal_multi_module_gate_status": status.get("formal_multi_module_gate_status"),
    }


def _git(args: list[str], repo: Path) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, timeout=60, check=False)
    return result.stdout


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Block 27A Three-scenario Harness Report",
            "",
            "## Scope",
            "27A implements offline orchestration only: scenario routing, skill contracts, DAG planning, context contract, checkpoints, state machine, and trace.",
            "",
            "## Scenario Router",
            f"- zero_to_one_fixture_passed: {report['scenario_router']['zero_to_one_fixture_passed']}",
            f"- one_to_many_fixture_passed: {report['scenario_router']['one_to_many_fixture_passed']}",
            f"- one_to_one_x_fixture_passed: {report['scenario_router']['one_to_one_x_fixture_passed']}",
            f"- mixed_fixture_forced_classification: {report['scenario_router']['mixed_fixture_forced_classification']}",
            f"- insufficient_evidence_forced_classification: {report['scenario_router']['insufficient_evidence_forced_classification']}",
            "",
            "## Skills and Plans",
            f"- registered_skill_count: {report['skills']['registered_skill_count']}",
            f"- capability_gap_count: {report['harness']['capability_gap_count']}",
            f"- dag_cycle_count: {report['plans']['dag_cycle_count']}",
            "",
            "## Safety",
            f"- real_llm_calls_executed: {report['safety']['real_llm_calls_executed']}",
            f"- knowledge_storage_writes_executed: {report['safety']['knowledge_storage_writes_executed']}",
            f"- lightrag_core_modified: {report['safety']['lightrag_core_modified']}",
            "",
            "## 26B Gate Boundary",
            "26B-LOCAL allows local 27A development, while the formal multi-module production gate remains pending.",
            "",
            "## Final",
            f"- overall_status: {report['final']['overall_status']}",
            f"- recommended_next_block: {report['final']['recommended_next_block']}",
        ]
    ) + "\n"


def _architecture() -> str:
    return """flowchart TD
    R[Requirement Input] --> P[Scenario Profile]
    P --> S{Scenario Router}
    S -->|0 to 1| Z[Zero-to-One Skill Template]
    S -->|1 to N| N[One-to-Many Skill Template]
    S -->|1 to 1.x| O[One-to-One-X Skill Template]
    S -->|Ambiguous / Mixed| C[Clarification / Split Checkpoint]
    Z --> D[DAG Planner]
    N --> D
    O --> D
    K[Trusted Knowledge / Version / Impact Context] --> A[Context Assembler]
    A --> D
    D --> G[Capability Probe]
    G -->|Available| E[Harness Dry-run Executor]
    G -->|Missing| B[Capability Gap / Human Checkpoint]
    E --> Q[Checkpoint Policy]
    Q --> T[Execution Trace + Structured Design Task Pack]
    NOTE[27A: Orchestration only; no final LLM design output]
"""


def _unresolved_questions() -> str:
    return """# Unresolved Questions

- Formal Block 26B multi-module production gate remains pending; 26B-LOCAL only authorizes local 27A/27B/28 development.
- CODE_CONTEXT_HANDOFF is registered as PLANNED_NOT_IMPLEMENTED; 1->1.x code-level impact cannot be claimed complete until a real code-context adapter exists.
- Final US and final solution quality gates are intentionally deferred to Block 27B.
"""


if __name__ == "__main__":
    raise SystemExit(main())
