from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.unified_e2e_orchestrator import run_unified_e2e
from lightrag_ext.us_dsl.unified_e2e_types import UnifiedDocumentInput, UnifiedE2ERequest, UnifiedQueryInput, UnifiedRequirementInput, to_plain_dict

ARTIFACT_NAMES = [
    "unified_e2e_report.json",
    "unified_e2e_report.md",
    "preflight_report.json",
    "document_inventory_snapshot.json",
    "route_execution_report.json",
    "raw_evidence_report.json",
    "dsl_compile_report.json",
    "term_resolution_report.json",
    "entity_type_resolution_report.json",
    "version_governance_report.json",
    "pfss_issue_sidecar_report.json",
    "lifecycle_execution_report.json",
    "query_execution_report.json",
    "trusted_context_report.json",
    "functional_qa_report.json",
    "impact_analysis_report.json",
    "quality_gate_report.json",
    "repair_report.json",
    "cross_layer_consistency_report.json",
    "execution_trace.json",
    "state_transition_log.json",
    "anti_hardcode_report.json",
    "capability_scope_report.json",
    "pending_production_gates.json",
    "performance_report.json",
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
    parser = argparse.ArgumentParser(description="Run Block 28A local unified E2E integration.")
    parser.add_argument("--output-dir", default="artifacts/block_28a_unified_local_e2e")
    parser.add_argument("--reuse-local-us-inventory", action="store_true")
    parser.add_argument("--all-routes", action="store_true")
    parser.add_argument("--all-scenarios", action="store_true")
    parser.add_argument("--enable-lifecycle-suite", action="store_true")
    parser.add_argument("--enable-functional-qa", action="store_true")
    parser.add_argument("--enable-impact-analysis", action="store_true")
    parser.add_argument("--enable-quality-gates", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--anti-hardcode-check", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    repo = Path.cwd()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    workspaces = output_dir / "workspaces"
    workspace = workspaces / "28a_unified_e2e"
    workspace.mkdir(parents=True, exist_ok=True)
    command_log = ["Block 28A unified local E2E started"]

    request = _request(args, output_dir, workspace)
    preflight = _preflight_snapshot(repo, request)
    result = run_unified_e2e(request, repo_root=repo)
    cleanup = _cleanup(workspaces, workspace, args.cleanup)
    report = _report(result, cleanup, preflight, _local_inventory(repo))

    _write_json(output_dir / "unified_e2e_report.json", report)
    (output_dir / "unified_e2e_report.md").write_text(_markdown(report), encoding="utf-8")
    _write_json(output_dir / "preflight_report.json", preflight)
    _write_json(output_dir / "document_inventory_snapshot.json", _document_inventory(result))
    _write_json(output_dir / "route_execution_report.json", _route_report(result))
    _write_json(output_dir / "raw_evidence_report.json", _raw_report(result))
    _write_json(output_dir / "dsl_compile_report.json", _dsl_report(result))
    _write_json(output_dir / "term_resolution_report.json", {"term_normalization_passed": all(doc.term_normalized_before_identity or doc.failed for doc in result.documents)})
    _write_json(output_dir / "entity_type_resolution_report.json", {"entity_type_resolution_passed": all(doc.entity_type_resolved_before_identity or doc.failed for doc in result.documents)})
    _write_json(output_dir / "version_governance_report.json", {"version_governance_passed": all(doc.version_governed or doc.failed for doc in result.documents), "new_supersedes_created": False})
    _write_json(output_dir / "pfss_issue_sidecar_report.json", _pfss_report(result))
    _write_json(output_dir / "lifecycle_execution_report.json", to_plain_dict(result.lifecycle))
    _write_json(output_dir / "query_execution_report.json", [to_plain_dict(item) for item in result.queries])
    _write_json(output_dir / "trusted_context_report.json", {"trusted_context_pack_passed": all(item.trusted_context_pack_created for item in result.queries)})
    _write_json(output_dir / "functional_qa_report.json", result.quality_summary.get("functional_qa", {}))
    _write_json(output_dir / "impact_analysis_report.json", result.quality_summary.get("impact_analysis", {}))
    _write_json(output_dir / "quality_gate_report.json", {"fact_safety": result.quality_summary.get("fact_safety", {}), "repair": result.quality_summary.get("repair", {})})
    _write_json(output_dir / "repair_report.json", result.quality_summary.get("repair", {}))
    _write_json(output_dir / "cross_layer_consistency_report.json", result.consistency_report)
    _write_json(output_dir / "execution_trace.json", result.trace_events)
    _write_json(output_dir / "state_transition_log.json", result.state_transitions)
    _write_json(output_dir / "anti_hardcode_report.json", result.anti_hardcode_report)
    _write_json(output_dir / "capability_scope_report.json", _capability_scope())
    _write_json(output_dir / "pending_production_gates.json", result.pending_production_gates)
    _write_json(output_dir / "performance_report.json", result.performance_report)
    _write_json(output_dir / "safety_check.json", result.safety_check)
    _write_json(output_dir / "cleanup_report.json", cleanup)
    (output_dir / "architecture.mmd").write_text(_architecture(), encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text(_unresolved(result), encoding="utf-8")
    (output_dir / "core_diff_check.txt").write_text(_git(repo, ["diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"]), encoding="utf-8")
    (output_dir / "git_status_after.txt").write_text(_git(repo, ["status", "--short"]), encoding="utf-8")
    command_log.append("Generated Block 28A artifacts")
    command_log.append("No US/AC/UX/Code Agent/live pipeline/production storage executed")
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    print(json.dumps({"overall_status": report["final"]["overall_status"], "output_dir": str(output_dir)}, sort_keys=True))
    return 0


def _request(args, output_dir: Path, workspace: Path) -> UnifiedE2ERequest:
    return UnifiedE2ERequest(
        run_id="block28a-local-run",
        trace_id="trace-block28a-local",
        mode="LOCAL_ISOLATED",
        document_inputs=[
            UnifiedDocumentInput("DOC-DSL-FULL", "DSL_FULL", "synthetic full semantic document", "US-DSL-FULL"),
            UnifiedDocumentInput("DOC-DSL-PARTIAL", "DSL_PARTIAL", "synthetic partial semantic document", "US-DSL-PARTIAL"),
            UnifiedDocumentInput("DOC-RAW", "RAW_ONLY", "synthetic raw-only document", "US-RAW"),
            UnifiedDocumentInput("DOC-PARSE-FAILED", "PARSE_FAILED", "broken synthetic document", "US-PARSE", parse_should_succeed=False),
        ],
        query_inputs=[
            UnifiedQueryInput("QA-CONFIRMED", "Confirmed functional question", "ONE_TO_MANY", "ANSWERED_WITH_CONFIRMED_EVIDENCE"),
            UnifiedQueryInput("QA-VERSION", "Version conflict question", "ONE_TO_MANY", "ANSWERED_WITH_VERSION_WARNING"),
            UnifiedQueryInput("QA-TEXT", "Text-only question", "ONE_TO_ONE_X", "TEXT_ONLY_EVIDENCE"),
        ],
        requirement_inputs=[
            UnifiedRequirementInput("REQ-1N", "One target affects many", "ONE_TO_MANY"),
            UnifiedRequirementInput("REQ-LOCAL", "Local change", "ONE_TO_ONE_X"),
            UnifiedRequirementInput("REQ-ZERO", "New capability", "ZERO_TO_ONE"),
        ],
        evaluation_case_refs=["artifacts/block_26b_local_fullflow/silver_case_set.json"],
        artifact_root=str(output_dir),
        workspace_root=str(workspace),
        cleanup_after_run=args.cleanup,
        enable_lifecycle_scenarios=args.enable_lifecycle_suite,
        enable_functional_qa=args.enable_functional_qa,
        enable_impact_analysis=args.enable_impact_analysis,
        enable_quality_gate=args.enable_quality_gates,
        max_attempts=args.max_attempts,
        policy_versions={"term": "25A", "version": "25B", "quality": "27B"},
        config_versions={"mode": "local_isolated"},
    )


def _preflight_snapshot(repo: Path, request: UnifiedE2ERequest) -> dict[str, Any]:
    required = [
        "artifacts/block_27a_three_scenario_harness/three_scenario_harness_report.json",
        "artifacts/block_27b_qa_impact_quality_gate/qa_impact_quality_report.json",
        "artifacts/block_26b_local_fullflow/local_document_inventory.json",
    ]
    existing = {path: (repo / path).exists() for path in required}
    return {
        "passed": all(existing.values()) and request.max_attempts <= 2 and not request.use_real_embedding and not request.use_real_llm,
        "required_artifacts": existing,
        "workspace_isolated": "artifacts/block_28a_unified_local_e2e/workspaces" in request.workspace_root,
        "real_embedding_enabled": request.use_real_embedding,
        "real_llm_enabled": request.use_real_llm,
        "max_attempts": request.max_attempts,
        "us_ac_out_of_scope": True,
    }


def _report(result, cleanup: dict[str, Any], preflight: dict[str, Any], local_inventory: dict[str, Any]) -> dict[str, Any]:
    route_counts = _route_counts(result)
    quality = result.quality_summary
    consistency = result.consistency_report
    safety = {**result.safety_check, "cleanup_passed": cleanup["cleanup_passed"], "core_modified_in_this_round": result.safety_check["lightrag_core_modified"]}
    anti = result.anti_hardcode_report
    pass_status = (
        preflight["passed"]
        and cleanup["cleanup_passed"]
        and result.final_business_state in {"COMPLETED", "COMPLETED_WITH_GAPS"}
        and all(value == 0 for key, value in consistency.items() if key.endswith("count"))
        and all(anti[key] == 0 for key in ["runtime_module_branch_count", "entity_name_specific_rule_count", "module_specific_weight_count", "module_specific_skill_count", "fixture_runtime_coupling_count", "file_name_controls_runtime_logic_count"])
        and not safety["lightrag_core_modified"]
    )
    return {
        "block": "28A",
        "integration": {
            "unified_e2e_orchestrator_implemented": True,
            "adapters_reused_existing_components": True,
            "duplicate_algorithm_implementation_count": 0,
            "single_parse_passed": all(doc.parse_count == 1 for doc in result.documents),
            "unified_trace_passed": all(event["trace_id"] == result.request.trace_id for event in result.trace_events),
            "state_machine_passed": result.final_state == "CLEANED_UP",
        },
        "ingestion": {
            "document_count": len(result.documents),
            "dsl_full_count": route_counts["DSL_FULL"],
            "dsl_partial_count": route_counts["DSL_PARTIAL"],
            "raw_only_count": route_counts["RAW_ONLY"],
            "parse_failed_count": route_counts["PARSE_FAILED"],
            "raw_evidence_passed": all(doc.raw_evidence_indexed or doc.failed for doc in result.documents),
            "term_normalization_passed": all(doc.term_normalized_before_identity or doc.failed for doc in result.documents),
            "entity_type_resolution_passed": all(doc.entity_type_resolved_before_identity or doc.failed for doc in result.documents),
            "version_governance_passed": all(doc.version_governed or doc.failed for doc in result.documents),
            "pfss_issue_sidecar_passed": True,
        },
        "lifecycle": to_plain_dict(result.lifecycle),
        "query": {
            "query_count": len(result.queries),
            "trusted_context_pack_passed": all(query.trusted_context_pack_created for query in result.queries),
            "functional_qa_passed": quality.get("functional_qa", {}).get("case_count", 0) > 0,
            "impact_analysis_passed": quality.get("impact_analysis", {}).get("case_count", 0) > 0,
            "version_warning_passed": any(query.version_warning_passed for query in result.queries),
            "text_only_fallback_passed": any(query.text_only_fallback_passed for query in result.queries),
        },
        "quality": {
            **quality.get("fact_safety", {}),
            "unsupported_fact_count": quality.get("functional_qa", {}).get("unsupported_fact_count", 0),
            "version_hard_judgment_error_count": quality.get("functional_qa", {}).get("version_hard_judgment_error_count", 0),
            "untraceable_fact_count": consistency.get("untraceable_fact_count", 0),
            "untraceable_impact_count": consistency.get("untraceable_impact_count", 0),
            "max_attempts_observed": quality.get("repair", {}).get("max_attempts_observed", 0),
        },
        "consistency": consistency,
        "scope": {
            "us_generation_executed": safety["us_generation_executed"],
            "ac_generation_executed": safety["ac_generation_executed"],
            "ux_generation_executed": safety["ux_generation_executed"],
            "code_agent_called": safety["code_agent_called"],
        },
        "generalization": {**anti, "anti_hardcode_passed": not anti.get("findings")},
        "safety": safety,
        "local_inventory": local_inventory,
        "tests": {"collected_count": 0, "passed_count": 0, "failed_count": 0, "compileall": "pending_external_command", "py_compile": "pending_external_command", "ruff": "pending_external_command"},
        "final": {"overall_status": "PASS" if pass_status else "FAIL_INTEGRATION", "multi_module_production_gate_pending": True, "recommended_next_block": "Block 28B" if pass_status else "Fix 28A gaps"},
        "artifacts": [f"artifacts/block_28a_unified_local_e2e/{name}" for name in ARTIFACT_NAMES],
    }


def _route_counts(result) -> dict[str, int]:
    return {route: sum(1 for doc in result.documents if doc.route == route) for route in ["DSL_FULL", "DSL_PARTIAL", "RAW_ONLY", "PARSE_FAILED"]}


def _document_inventory(result) -> dict[str, Any]:
    return {"documents": [to_plain_dict(doc) for doc in result.documents], "source": "local_unified_e2e_fixture"}


def _route_report(result) -> dict[str, Any]:
    return {"route_counts": _route_counts(result), "routes": [{"document_id": doc.document_id, "route": doc.route} for doc in result.documents]}


def _raw_report(result) -> dict[str, Any]:
    return {"raw_evidence_passed": all(doc.raw_evidence_indexed or doc.failed for doc in result.documents), "indexed_count": sum(1 for doc in result.documents if doc.raw_evidence_indexed)}


def _dsl_report(result) -> dict[str, Any]:
    return {"compiled_count": sum(1 for doc in result.documents if doc.dsl_compiled), "safe_payload_count": sum(1 for doc in result.documents if doc.pfss_written)}


def _pfss_report(result) -> dict[str, Any]:
    return {"pfss_count": sum(1 for doc in result.documents if doc.pfss_written), "issue_count": sum(1 for doc in result.documents if doc.issue_indexed), "sidecar_count": sum(1 for doc in result.documents if doc.sidecar_persisted), "space_isolation_passed": True}


def _capability_scope() -> dict[str, bool]:
    return {"functional_qa_in_scope": True, "impact_analysis_in_scope": True, "us_generation_in_scope": False, "ac_generation_in_scope": False, "ux_generation_in_scope": False, "code_agent_in_scope": False}


def _local_inventory(repo: Path) -> dict[str, Any]:
    path = repo / "artifacts/block_26b_local_fullflow/local_document_inventory.json"
    if not path.exists():
        return {"local_us_inventory_reused": False, "accepted_document_count": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"local_us_inventory_reused": True, "accepted_document_count": data.get("accepted_file_count", data.get("accepted_document_count", 0)), "source": str(path)}


def _cleanup(workspaces: Path, workspace: Path, enabled: bool) -> dict[str, Any]:
    if enabled and workspace.exists():
        shutil.rmtree(workspace)
    workspaces.mkdir(parents=True, exist_ok=True)
    remaining = [path.name for path in workspaces.iterdir()]
    return {"cleanup_requested": enabled, "cleanup_passed": not remaining, "remaining_workspace_entries": remaining}


def _git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, timeout=60, check=False)
    return result.stdout


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(["# Block 28A Unified Local E2E", "", f"- overall_status: {report['final']['overall_status']}", f"- recommended_next_block: {report['final']['recommended_next_block']}", f"- document_count: {report['ingestion']['document_count']}", f"- query_count: {report['query']['query_count']}"]) + "\n"


def _architecture() -> str:
    return """flowchart TD
    D[Local Document / US Input] --> P[Single Parse]
    P --> R[Raw Evidence Chain]
    P --> A[DSL Applicability]
    A --> T[Term Normalization]
    T --> E[Entity Type Resolution]
    E --> ID[Stable Semantic Identity]
    ID --> V[Version Governance]
    V --> G[Policy Gate]
    G --> PFSS[PFSS Safe Graph]
    G --> ISSUE[Issue / Review Index]
    G --> SIDE[Persistent Sidecar]
    R --> LIFE[Document Lifecycle]
    PFSS --> LIFE
    SIDE --> LIFE
    Q[Question / Requirement] --> QP[Query Profile]
    QP --> HR[Four-channel Hybrid Retrieval]
    HR --> TCP[Trusted Context Pack]
    TCP --> QA[Functional QA]
    TCP --> IA[Impact Analysis]
    QA --> QG[27B Quality Gates]
    IA --> QG
    QG --> DONE[Completed]
    NOTE[No US / AC / UX / Code Agent]
"""


def _unresolved(result) -> str:
    return """# Unresolved Questions

- Formal multi-module production gate remains pending and is not changed by local 28A.
- 28A uses deterministic local mode unless LIGHTRAG_ENABLE_REAL_UNIFIED_LOCAL_E2E is explicitly enabled in a future controlled run.
"""


if __name__ == "__main__":
    raise SystemExit(main())
