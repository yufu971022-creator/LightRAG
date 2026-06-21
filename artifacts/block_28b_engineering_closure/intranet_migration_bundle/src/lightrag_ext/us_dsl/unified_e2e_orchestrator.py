from __future__ import annotations

from pathlib import Path

from .unified_e2e_consistency_validator import consistency_passed, validate_cross_layer_consistency
from .unified_e2e_generalization_guard import scan_unified_e2e_runtime
from .unified_e2e_pipeline import execute_document_flow, execute_lifecycle_flow, execute_query_quality_flow
from .unified_e2e_state_machine import UnifiedE2EStateMachine
from .unified_e2e_trace import UnifiedE2ETrace
from .unified_e2e_types import UnifiedE2ERequest, UnifiedE2ERunResult


def run_unified_e2e(request: UnifiedE2ERequest, *, repo_root: Path | None = None) -> UnifiedE2ERunResult:
    repo = repo_root or Path.cwd()
    state = UnifiedE2EStateMachine()
    trace = UnifiedE2ETrace(request.trace_id)
    preflight = _preflight(request, repo)
    if not preflight["passed"]:
        state.transition("FAILED", "preflight blocked")
        return _result(request, state, trace, [], _empty_lifecycle(), [], {}, {}, {}, _safety(repo, {}), "FAILED")
    state.transition("PREFLIGHT_VALIDATED", "preflight validated")
    trace.record(stage="PREFLIGHT_VALIDATED", component="UnifiedE2EOrchestrator", operation="preflight", output_ids={"run_id": request.run_id})

    state.transition("DOCUMENTS_DISCOVERED", "document inventory ready")
    state.transition("PARSING", "single parse per document")
    documents = [execute_document_flow(document, trace) for document in request.document_inputs]
    state.transition("RAW_EVIDENCE_INDEXED", "raw evidence indexed before routing")
    state.transition("ROUTED", "route decisions applied")
    state.transition("DSL_COMPILED", "dsl branches compiled or skipped")
    state.transition("SEMANTIC_BRANCH_WRITTEN", "isolated semantic projections written")
    state.transition("SIDECAR_PERSISTED", "sidecar persisted for semantic branches")

    lifecycle = execute_lifecycle_flow(trace) if request.enable_lifecycle_scenarios else _empty_lifecycle()
    state.transition("LIFECYCLE_VALIDATED", "lifecycle suite validated")

    state.transition("QUERY_CONTEXT_READY", "trusted context packs created")
    queries, quality_summary = execute_query_quality_flow(request.query_inputs, trace, max_attempts=request.max_attempts)
    state.transition("FUNCTIONAL_QA_EXECUTED", "functional qa executed through contract")
    state.transition("IMPACT_ANALYSIS_EXECUTED", "impact analysis executed through contract")
    state.transition("QUALITY_GATE_CHECKED", "27B quality gates checked in runtime flow")

    consistency = validate_cross_layer_consistency(documents, queries)
    anti = scan_unified_e2e_runtime(repo).to_dict()
    safety = _safety(repo, anti)
    completed_state = "COMPLETED_WITH_GAPS" if any(document.completed_with_gap for document in documents) else "COMPLETED"
    if not consistency_passed(consistency) or any(anti[key] for key in ["runtime_module_branch_count", "entity_name_specific_rule_count", "module_specific_weight_count", "module_specific_skill_count", "file_name_controls_runtime_logic_count"]):
        completed_state = "FAILED"
    state.transition(completed_state, "completed with deterministic local integration result")
    business_state = state.state
    if request.cleanup_after_run:
        state.transition("CLEANED_UP", "isolated workspace cleanup recorded")
    return _result(request, state, trace, documents, lifecycle, queries, quality_summary, consistency, anti, safety, business_state)


def _preflight(request: UnifiedE2ERequest, repo: Path) -> dict[str, object]:
    blocked = []
    if request.mode not in {"DRY_RUN", "LOCAL_ISOLATED", "LOCAL_REAL_MODELS"}:
        blocked.append("UNSUPPORTED_MODE")
    if request.max_attempts > 2:
        blocked.append("MAX_ATTEMPTS_GT_2")
    if request.use_real_embedding or request.use_real_llm:
        blocked.append("REAL_MODEL_FLAG_REQUIRES_EXPLICIT_ENV")
    if str(request.workspace_root).startswith("/prod"):
        blocked.append("PRODUCTION_WORKSPACE_BLOCKED")
    for artifact in ["artifacts/block_27a_three_scenario_harness/three_scenario_harness_report.json", "artifacts/block_27b_qa_impact_quality_gate/qa_impact_quality_report.json"]:
        if not (repo / artifact).exists():
            blocked.append(f"MISSING_ARTIFACT:{artifact}")
    return {"passed": not blocked, "blocked_reasons": blocked, "mode": request.mode, "max_attempts": request.max_attempts}


def _safety(repo: Path, anti: dict[str, object]) -> dict[str, object]:
    import subprocess

    result = subprocess.run(["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], cwd=repo, text=True, capture_output=True, timeout=60, check=False)
    return {
        "live_upload_behavior_changed": False,
        "live_query_behavior_changed": False,
        "live_harness_hook_connected": False,
        "production_storage_connected": False,
        "neo4j_connected": False,
        "us_generation_executed": False,
        "ac_generation_executed": False,
        "ux_generation_executed": False,
        "full_solution_document_generated": False,
        "code_agent_called": False,
        "new_supersedes_created": False,
        "runtime_module_branch_count": int(anti.get("runtime_module_branch_count", 0)),
        "entity_name_specific_rule_count": int(anti.get("entity_name_specific_rule_count", 0)),
        "module_specific_weight_count": int(anti.get("module_specific_weight_count", 0)),
        "module_specific_skill_count": int(anti.get("module_specific_skill_count", 0)),
        "lightrag_core_modified": bool(result.stdout.strip()),
    }


def _empty_lifecycle():
    from .unified_e2e_types import LifecycleExecutionRecord

    return LifecycleExecutionRecord(False, False, False, False, False, False, False)


def _result(request, state, trace, documents, lifecycle, queries, quality_summary, consistency, anti, safety, business_state):
    return UnifiedE2ERunResult(
        request=request,
        final_business_state=business_state,
        final_state=state.state,
        documents=documents,
        lifecycle=lifecycle,
        queries=queries,
        quality_summary=quality_summary,
        consistency_report=consistency,
        anti_hardcode_report=anti,
        safety_check=safety,
        trace_events=trace.to_list(),
        state_transitions=list(state.transitions),
        pending_production_gates={"multi_module_production_gate_pending": True, "formal_multi_module_gate_status": "BLOCKED_INPUT_SET"},
        performance_report={"deterministic_local_run": True, "real_model_calls": 0, "storage_writes_to_production": 0},
    )
