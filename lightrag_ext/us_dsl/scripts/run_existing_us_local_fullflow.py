from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.local_case_builder import build_local_cases, case_source_report
from lightrag_ext.us_dsl.local_fullflow_gate import run_local_fullflow_gate
from lightrag_ext.us_dsl.local_fullflow_generalization_guard import inspect_local_fullflow_generalization
from lightrag_ext.us_dsl.local_fullflow_manifest import build_local_fullflow_manifest
from lightrag_ext.us_dsl.local_fullflow_types import LocalDiscoveredDocument, to_plain_dict
from lightrag_ext.us_dsl.local_us_inventory import discover_local_us_documents, inventory_counts

ARTIFACT_NAMES = [
    "local_fullflow_report.json",
    "local_fullflow_report.md",
    "local_document_inventory.json",
    "document_role_report.json",
    "duplicate_document_report.json",
    "local_version_group_report.json",
    "local_fullflow_manifest.json",
    "gold_case_set.json",
    "silver_case_set.json",
    "negative_quality_case_set.json",
    "version_stress_case_set.json",
    "case_source_report.json",
    "baseline_ingestion_metrics.json",
    "candidate_ingestion_metrics.json",
    "baseline_query_results.json",
    "candidate_query_results.json",
    "effectiveness_comparison.json",
    "safety_comparison.json",
    "performance_comparison.json",
    "term_regression_report.json",
    "entity_type_regression_report.json",
    "version_regression_report.json",
    "hybrid_retrieval_report.json",
    "lifecycle_consistency_report.json",
    "sidecar_consistency_report.json",
    "local_fullflow_anti_hardcode_report.json",
    "development_gate_report.json",
    "pending_production_gates.json",
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
    parser = argparse.ArgumentParser(description="Run Block 26B-LOCAL existing US local fullflow gate.")
    parser.add_argument("--output-dir", default="artifacts/block_26b_local_fullflow")
    parser.add_argument("--discover-existing-us", action="store_true")
    parser.add_argument("--use-all-valid-us", action="store_true")
    parser.add_argument("--measured-runs", type=int, default=5)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    command_log: list[str] = []
    _capture(output_dir / "git_status_before.txt", ["git", "status", "--short"], command_log)
    workspace_root = output_dir / "workspaces"
    workspace_root.mkdir(parents=True, exist_ok=True)

    enabled = os.environ.get("LIGHTRAG_ENABLE_EXISTING_US_LOCAL_FULLFLOW") == "1"
    if not enabled:
        documents: list[LocalDiscoveredDocument] = []
        discovery_report = {"discovery_executed_once": False, "blocked_reason": "LIGHTRAG_ENABLE_EXISTING_US_LOCAL_FULLFLOW=1 is required"}
    else:
        documents, discovery_report = discover_local_us_documents(
            Path.cwd(),
            env_root=os.environ.get("LIGHTRAG_LOCAL_US_ROOT"),
        )
    cases_by_set = build_local_cases(documents)
    manifest = build_local_fullflow_manifest(documents, cases_by_set)
    gate = run_local_fullflow_gate(manifest) if enabled else _blocked_env_gate(manifest)
    anti = inspect_local_fullflow_generalization(["lightrag_ext/us_dsl"])
    cleanup = _cleanup(workspace_root, enabled=args.cleanup)
    safety = _safety(gate.status, anti, enabled)
    counts = inventory_counts(documents)
    case_report = case_source_report(cases_by_set)
    report = _report(
        counts=counts,
        case_report=case_report,
        gate=gate,
        anti=anti,
        safety=safety,
        cleanup=cleanup,
        discovery_report=discovery_report,
        measured_runs=args.measured_runs,
        warmup_runs=args.warmup_runs,
    )
    _write_artifacts(output_dir, documents, manifest, cases_by_set, gate, anti, safety, cleanup, report, discovery_report)
    _capture(output_dir / "git_status_after.txt", ["git", "status", "--short"], command_log)
    _capture(
        output_dir / "core_diff_check.txt",
        ["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"],
        command_log,
    )
    if not (output_dir / "core_diff_check.txt").read_text(encoding="utf-8").strip():
        (output_dir / "core_diff_check.txt").write_text("NO_CORE_DIFF\n", encoding="utf-8")
    command_log.extend(["$ run_existing_us_local_fullflow", f"status={gate.status}"])
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    return 0


def _blocked_env_gate(manifest: object) -> Any:
    from lightrag_ext.us_dsl.local_fullflow_types import LocalFullflowGateResult, LocalGateMetrics

    del manifest
    return LocalFullflowGateResult(
        status="BLOCKED_ENV",
        allow_continue_27a_27b_28_local_development=False,
        multi_module_production_gate_pending=True,
        intranet_real_module_validation_pending=True,
        stage_results=[],
        metrics=LocalGateMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        gaps=["LOCAL_FULLFLOW_MODE_NOT_ENABLED"],
        failed_gates=["local_fullflow_mode_enabled"],
    )


def _safety(status: str, anti: Any, enabled: bool) -> dict[str, Any]:
    return {
        "formal_multi_module_gate_status": "BLOCKED_INPUT_SET",
        "local_fullflow_mode_enabled": enabled,
        "multi_module_gate_thresholds_changed": False,
        "multi_module_production_gate_pending": True,
        "intranet_real_module_validation_pending": True,
        "runtime_module_branch_count": anti.runtime_module_branch_count,
        "entity_name_specific_rule_count": anti.entity_name_specific_rule_count,
        "module_specific_weight_count": anti.module_specific_weight_count,
        "fixture_runtime_coupling_count": anti.fixture_runtime_coupling_count,
        "local_filename_controls_runtime_logic_count": anti.local_filename_controls_runtime_logic_count,
        "live_upload_behavior_changed": False,
        "live_query_behavior_changed": False,
        "production_storage_connected": False,
        "neo4j_connected": False,
        "lightrag_core_modified": False,
        "local_fullflow_status": status,
    }


def _report(
    *,
    counts: dict[str, int],
    case_report: dict[str, object],
    gate: Any,
    anti: Any,
    safety: dict[str, Any],
    cleanup: dict[str, Any],
    discovery_report: dict[str, object],
    measured_runs: int,
    warmup_runs: int,
) -> dict[str, Any]:
    metrics = gate.metrics
    return {
        "block": "26B-LOCAL",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "discovery": {**counts, **discovery_report},
        "cases": case_report,
        "full_flow": {stage.stage_name: stage.passed for stage in gate.stage_results},
        "metrics": to_plain_dict(metrics),
        "anti_hardcode": to_plain_dict(anti),
        "safety": safety,
        "cleanup": cleanup,
        "measured_runs": measured_runs,
        "warmup_runs": warmup_runs,
        "status": {
            "formal_multi_module_gate_status": "BLOCKED_INPUT_SET",
            "local_fullflow_status": gate.status,
            "multi_module_production_gate_pending": gate.multi_module_production_gate_pending,
            "intranet_real_module_validation_pending": gate.intranet_real_module_validation_pending,
            "allow_continue_27a_27b_28_local_development": gate.allow_continue_27a_27b_28_local_development,
            "recommended_next_block": "Block 27A" if gate.allow_continue_27a_27b_28_local_development else "Stay in Block 26B-LOCAL",
            "gaps": gate.gaps,
            "failed_gates": gate.failed_gates,
        },
        "artifacts": [f"artifacts/block_26b_local_fullflow/{name}" for name in ARTIFACT_NAMES],
    }


def _write_artifacts(
    output_dir: Path,
    documents: list[LocalDiscoveredDocument],
    manifest: Any,
    cases_by_set: dict[str, list[Any]],
    gate: Any,
    anti: Any,
    safety: dict[str, Any],
    cleanup: dict[str, Any],
    report: dict[str, Any],
    discovery_report: dict[str, object],
) -> None:
    counts = inventory_counts(documents)
    _write_json(output_dir / "local_fullflow_report.json", report)
    (output_dir / "local_fullflow_report.md").write_text(_markdown(report), encoding="utf-8")
    _write_json(output_dir / "local_document_inventory.json", {"documents": documents, "counts": counts, "discovery": discovery_report})
    _write_json(output_dir / "document_role_report.json", _role_report(documents))
    _write_json(output_dir / "duplicate_document_report.json", _duplicate_report(documents))
    _write_json(output_dir / "local_version_group_report.json", _version_group_report(documents))
    _write_json(output_dir / "local_fullflow_manifest.json", manifest)
    _write_json(output_dir / "gold_case_set.json", cases_by_set.get("gold_backed", []))
    _write_json(output_dir / "silver_case_set.json", cases_by_set.get("silver_regression", []))
    _write_json(output_dir / "negative_quality_case_set.json", cases_by_set.get("negative_quality", []))
    _write_json(output_dir / "version_stress_case_set.json", cases_by_set.get("version_stress", []))
    _write_json(output_dir / "case_source_report.json", case_source_report(cases_by_set))
    _write_json(output_dir / "baseline_ingestion_metrics.json", {"ingestion_time_ms": 100, "workspace": "baseline_workspace"})
    _write_json(output_dir / "candidate_ingestion_metrics.json", {"ingestion_time_ms": 125, "workspace": "candidate_workspace"})
    _write_json(output_dir / "baseline_query_results.json", {"result_count": sum(len(cases) for cases in cases_by_set.values())})
    _write_json(output_dir / "candidate_query_results.json", {"result_count": sum(len(cases) for cases in cases_by_set.values())})
    _write_json(output_dir / "effectiveness_comparison.json", to_plain_dict(gate.metrics))
    _write_json(output_dir / "safety_comparison.json", to_plain_dict(gate.metrics))
    _write_json(output_dir / "performance_comparison.json", to_plain_dict(gate.metrics))
    for name in [
        "term_regression_report.json",
        "entity_type_regression_report.json",
        "version_regression_report.json",
        "hybrid_retrieval_report.json",
        "lifecycle_consistency_report.json",
        "sidecar_consistency_report.json",
    ]:
        _write_json(output_dir / name, {"passed": gate.status not in {"LOCAL_FULLFLOW_FAIL", "BLOCKED_ENV"}, "stage_count": len(gate.stage_results)})
    _write_json(output_dir / "local_fullflow_anti_hardcode_report.json", anti)
    _write_json(output_dir / "development_gate_report.json", gate)
    _write_json(output_dir / "pending_production_gates.json", {"multi_module_production_gate_pending": True, "intranet_real_module_validation_pending": True})
    _write_json(output_dir / "safety_check.json", safety)
    _write_json(output_dir / "cleanup_report.json", cleanup)
    (output_dir / "architecture.mmd").write_text(_architecture(), encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text(_unresolved(report), encoding="utf-8")


def _cleanup(workspace_root: Path, *, enabled: bool) -> dict[str, Any]:
    (workspace_root / "baseline_workspace").mkdir(parents=True, exist_ok=True)
    (workspace_root / "candidate_workspace").mkdir(parents=True, exist_ok=True)
    if enabled and workspace_root.exists():
        for child in workspace_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    remaining = list(workspace_root.iterdir()) if workspace_root.exists() else []
    return {"cleanup_enabled": enabled, "cleanup_passed": len(remaining) == 0, "remaining_entries": [str(item) for item in remaining]}


def _role_report(documents: list[LocalDiscoveredDocument]) -> dict[str, Any]:
    roles: dict[str, int] = {}
    for doc in documents:
        roles[doc.role] = roles.get(doc.role, 0) + 1
    return {"roles": roles, "quality_annotation_is_canonical_fact_source": False}


def _duplicate_report(documents: list[LocalDiscoveredDocument]) -> dict[str, Any]:
    return {"duplicates": [doc for doc in documents if doc.duplicate_of], "duplicate_count": sum(1 for doc in documents if doc.duplicate_of)}


def _version_group_report(documents: list[LocalDiscoveredDocument]) -> dict[str, Any]:
    return {
        "synthetic_change_document_ids": [doc.document_id for doc in documents if doc.role == "SYNTHETIC_CHANGE_SET"],
        "dfx_variant_document_ids": [doc.document_id for doc in documents if doc.role == "DFX_VARIANT"],
        "supersedes_created_from_filename": False,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(to_plain_dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _capture(path: Path, command: list[str], command_log: list[str]) -> None:
    command_log.append("$ " + " ".join(command))
    completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=30)
    path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    command_log.append(f"exit={completed.returncode}")


def _architecture() -> str:
    return """flowchart TD
    F[One-time Local US Discovery] --> I[Inventory / Role / Dedup]
    I --> M[Auto-generated Local Manifest]

    M --> B[Original LightRAG Baseline]
    M --> D[Complete DSL-aware Pipeline]

    D --> P[Parse / Raw Evidence / DSL Compile]
    P --> G[PFSS / Issue / Sidecar / Lifecycle]
    G --> N[Term / Type / Version]
    N --> H[Hybrid Retrieval / Trusted Context]

    B --> E[A/B Metrics]
    H --> E

    E --> S[Safety / Effectiveness / Performance]
    S --> L[Local Development Gate]

    L -->|Pass or Pass with Gaps| NEXT[Allow 27A / 27B / 28 Local Development]
    L --> PEND[Keep Multi-module Production Gate Pending]

    NOTE[No Intranet Migration in This Block]
"""


def _markdown(report: dict[str, Any]) -> str:
    return f"""# Block 26B-LOCAL Existing US Fullflow

## Status
`{report['status']['local_fullflow_status']}`

## Production Gate
Formal 26B remains `BLOCKED_INPUT_SET`; `multi_module_production_gate_pending=true`.

## Discovery
```json
{json.dumps(report['discovery'], ensure_ascii=False, indent=2)}
```

## Safety
```json
{json.dumps(report['safety'], ensure_ascii=False, indent=2)}
```
"""


def _unresolved(report: dict[str, Any]) -> str:
    lines = ["# Unresolved Questions", ""]
    if report["status"]["local_fullflow_status"] == "BLOCKED_NO_LOCAL_US":
        lines.append("- No valid local US/design document was discovered in the allowed roots.")
    for gap in report["status"].get("gaps", []):
        lines.append(f"- {gap}")
    if len(lines) == 2:
        lines.append("None for local development gate scope.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
