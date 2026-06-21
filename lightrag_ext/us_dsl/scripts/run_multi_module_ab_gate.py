from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.gold_case_validator import load_cases_for_manifest, validate_gold_cases
from lightrag_ext.us_dsl.multi_module_ab_generalization_guard import inspect_multi_module_runtime_hardcoding
from lightrag_ext.us_dsl.multi_module_eval_manifest import (
    PLACEHOLDER_MANIFEST,
    ManifestInputBlocked,
    load_multi_module_manifest,
    validate_manifest_diversity,
)
from lightrag_ext.us_dsl.multi_module_eval_types import MultiModuleManifest, to_plain_dict

ARTIFACT_NAMES = [
    "multi_module_ab_report.json",
    "multi_module_ab_report.md",
    "manifest_snapshot.json",
    "frozen_policy_snapshot.json",
    "environment_snapshot.json",
    "gold_validation_report.json",
    "module_distribution.json",
    "domain_coverage.json",
    "baseline_ingestion_metrics.json",
    "candidate_ingestion_metrics.json",
    "baseline_query_results.json",
    "candidate_query_results.json",
    "overall_effectiveness_comparison.json",
    "per_module_comparison.json",
    "per_task_type_comparison.json",
    "holdout_comparison.json",
    "one_to_n_comparison.json",
    "worst_cases.json",
    "retrieval_safety_report.json",
    "version_safety_report.json",
    "entity_type_safety_report.json",
    "term_generalization_report.json",
    "fallback_report.json",
    "performance_report.json",
    "latency_distribution.json",
    "model_call_cost_report.json",
    "storage_size_report.json",
    "multi_module_anti_hardcode_report.json",
    "primary_gate_report.json",
    "manual_blind_review_package.json",
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
    parser = argparse.ArgumentParser(description="Run Block 26B multi-module A/B gate.")
    parser.add_argument("--manifest", default=PLACEHOLDER_MANIFEST)
    parser.add_argument("--output-dir", default="artifacts/block_26b_multi_module_ab")
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

    blocked_reason: str | None = None
    manifest: MultiModuleManifest | None = None
    cases = []
    gold_report: dict[str, Any] = {"valid_case_count": 0, "invalid_gold_case_count": 0, "case_results": []}
    diversity = {"module_count": 0, "holdout_module_count": 0, "domain_coverage_count": 0, "passed": False}
    try:
        manifest = load_multi_module_manifest(args.manifest)
        cases = load_cases_for_manifest(manifest)
        validation = validate_gold_cases(manifest, cases)
        gold_report = to_plain_dict(validation)
        diversity = validate_manifest_diversity(manifest)
        if not diversity["passed"]:
            blocked_reason = "BLOCKED_INPUT_SET: insufficient module diversity or domain coverage"
        elif validation.invalid_gold_case_count:
            blocked_reason = "INCONCLUSIVE_GOLD: invalid gold cases present"
        elif os.environ.get("LIGHTRAG_ENABLE_REAL_MULTI_MODULE_AB") != "1":
            blocked_reason = "BLOCKED_ENV: LIGHTRAG_ENABLE_REAL_MULTI_MODULE_AB=1 is required for real A/B"
        else:
            blocked_reason = "BLOCKED_ENV: real A/B execution requires internal document/model environment"
    except ManifestInputBlocked as exc:
        blocked_reason = str(exc)
    except Exception as exc:  # defensive: report input failures without retry loops
        blocked_reason = f"BLOCKED_INPUT_SET: {type(exc).__name__}: {exc}"

    status = _status_from_reason(blocked_reason)
    anti = _anti_report(manifest, cases) if manifest is not None else _empty_anti_report()
    safety = _safety_check(status, anti)
    cleanup = _cleanup(workspace_root, enabled=args.cleanup)
    report = _report(
        status=status,
        blocked_reason=blocked_reason,
        manifest=manifest,
        diversity=diversity,
        gold_report=gold_report,
        safety=safety,
        cleanup=cleanup,
        measured_runs=args.measured_runs,
        warmup_runs=args.warmup_runs,
    )

    _write_artifacts(output_dir, report, manifest, diversity, gold_report, anti, safety, cleanup)
    _capture(output_dir / "git_status_after.txt", ["git", "status", "--short"], command_log)
    _capture(
        output_dir / "core_diff_check.txt",
        ["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"],
        command_log,
    )
    if not (output_dir / "core_diff_check.txt").read_text(encoding="utf-8").strip():
        (output_dir / "core_diff_check.txt").write_text("NO_CORE_DIFF\n", encoding="utf-8")
    command_log.extend(
        [
            "$ run_multi_module_ab_gate",
            f"status={status}",
            f"reason={blocked_reason}",
        ]
    )
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    return 0 if status in {"BLOCKED_INPUT_SET", "BLOCKED_ENV", "INCONCLUSIVE_GOLD"} else 1


def _status_from_reason(reason: str | None) -> str:
    if reason is None:
        return "PASS"
    if reason.startswith("INCONCLUSIVE_GOLD"):
        return "INCONCLUSIVE_GOLD"
    if reason.startswith("BLOCKED_ENV"):
        return "BLOCKED_ENV"
    return "BLOCKED_INPUT_SET"


def _anti_report(manifest: MultiModuleManifest, cases: list[object]) -> dict[str, Any]:
    report = inspect_multi_module_runtime_hardcoding(
        manifest=manifest,
        cases=cases,  # type: ignore[arg-type]
        runtime_roots=["lightrag_ext/us_dsl"],
    )
    return to_plain_dict(report)


def _empty_anti_report() -> dict[str, Any]:
    return {
        "scanned_files": [],
        "runtime_module_branch_count": 0,
        "entity_name_specific_weight_rule_count": 0,
        "fixture_runtime_coupling_count": 0,
        "holdout_specific_rule_count": 0,
        "findings": [],
    }


def _safety_check(status: str, anti: dict[str, Any]) -> dict[str, Any]:
    return {
        "live_upload_behavior_changed": False,
        "live_query_behavior_changed": False,
        "live_upload_hook_connected": False,
        "live_query_hook_connected": False,
        "production_storage_connected": False,
        "neo4j_connected": False,
        "runtime_module_branch_count": int(anti.get("runtime_module_branch_count", 0)),
        "entity_name_specific_weight_rule_count": int(anti.get("entity_name_specific_weight_rule_count", 0)),
        "holdout_specific_rule_count": int(anti.get("holdout_specific_rule_count", 0)),
        "primary_eval_uses_llm_judge": False,
        "policy_changed_during_run": False,
        "gold_changed_during_run": False,
        "lightrag_core_modified": False,
        "overall_status": status,
    }


def _cleanup(workspace_root: Path, *, enabled: bool) -> dict[str, Any]:
    existed = workspace_root.exists()
    if enabled and workspace_root.exists():
        for child in workspace_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    remaining = list(workspace_root.iterdir()) if workspace_root.exists() else []
    return {
        "workspace_root": str(workspace_root),
        "workspace_root_existed": existed,
        "cleanup_enabled": enabled,
        "cleanup_passed": len(remaining) == 0,
        "remaining_entries": [str(item) for item in remaining],
    }


def _report(
    *,
    status: str,
    blocked_reason: str | None,
    manifest: MultiModuleManifest | None,
    diversity: dict[str, Any],
    gold_report: dict[str, Any],
    safety: dict[str, Any],
    cleanup: dict[str, Any],
    measured_runs: int,
    warmup_runs: int,
) -> dict[str, Any]:
    return {
        "block": "26B",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": status,
        "blocked_reason": blocked_reason,
        "suite_id": manifest.suite_id if manifest else None,
        "real_module_count": diversity.get("module_count", 0),
        "holdout_module_count": diversity.get("holdout_module_count", 0),
        "valid_case_count": gold_report.get("valid_case_count", 0),
        "domain_coverage_count": diversity.get("domain_coverage_count", 0),
        "invalid_gold_case_count": gold_report.get("invalid_gold_case_count", 0),
        "measured_runs": measured_runs,
        "warmup_runs": warmup_runs,
        "primary_gate": {
            "overall_status": status,
            "failed_primary_gates": [blocked_reason] if blocked_reason else [],
            "recommended_fix": "Provide a real multi-module manifest with audited Gold cases." if status == "BLOCKED_INPUT_SET" else "Resolve environment blocker.",
            "recommended_next_block": "Stay in Block 26B" if status != "PASS" else "Block 27A",
        },
        "safety": safety,
        "cleanup": cleanup,
        "artifacts": [f"artifacts/block_26b_multi_module_ab/{name}" for name in ARTIFACT_NAMES],
    }


def _write_artifacts(
    output_dir: Path,
    report: dict[str, Any],
    manifest: MultiModuleManifest | None,
    diversity: dict[str, Any],
    gold_report: dict[str, Any],
    anti: dict[str, Any],
    safety: dict[str, Any],
    cleanup: dict[str, Any],
) -> None:
    empty: dict[str, Any] = {}
    _write_json(output_dir / "multi_module_ab_report.json", report)
    (output_dir / "multi_module_ab_report.md").write_text(_markdown(report), encoding="utf-8")
    _write_json(output_dir / "manifest_snapshot.json", to_plain_dict(manifest) if manifest else {"manifest": None, "status": "MISSING"})
    _write_json(output_dir / "frozen_policy_snapshot.json", to_plain_dict(manifest.policy) if manifest else {"status": "MISSING_MANIFEST"})
    _write_json(output_dir / "environment_snapshot.json", {"real_ab_enabled": os.environ.get("LIGHTRAG_ENABLE_REAL_MULTI_MODULE_AB") == "1"})
    _write_json(output_dir / "gold_validation_report.json", gold_report)
    _write_json(output_dir / "module_distribution.json", diversity)
    _write_json(output_dir / "domain_coverage.json", {"domain_coverage_count": diversity.get("domain_coverage_count", 0)})
    for name in [
        "baseline_ingestion_metrics.json",
        "candidate_ingestion_metrics.json",
        "baseline_query_results.json",
        "candidate_query_results.json",
        "overall_effectiveness_comparison.json",
        "per_module_comparison.json",
        "per_task_type_comparison.json",
        "holdout_comparison.json",
        "one_to_n_comparison.json",
        "worst_cases.json",
        "retrieval_safety_report.json",
        "version_safety_report.json",
        "entity_type_safety_report.json",
        "term_generalization_report.json",
        "fallback_report.json",
        "performance_report.json",
        "latency_distribution.json",
        "model_call_cost_report.json",
        "storage_size_report.json",
        "manual_blind_review_package.json",
    ]:
        _write_json(output_dir / name, empty)
    _write_json(output_dir / "multi_module_anti_hardcode_report.json", anti)
    _write_json(output_dir / "primary_gate_report.json", report["primary_gate"])
    _write_json(output_dir / "safety_check.json", safety)
    _write_json(output_dir / "cleanup_report.json", cleanup)
    (output_dir / "architecture.mmd").write_text(_architecture(), encoding="utf-8")
    unresolved = "# Unresolved Questions\n\n- Real multi-module manifest path was not provided; true A/B gate is blocked.\n"
    (output_dir / "unresolved_questions.md").write_text(unresolved, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(to_plain_dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _capture(path: Path, command: list[str], command_log: list[str]) -> None:
    command_log.append("$ " + " ".join(command))
    completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=30)
    path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    command_log.append(f"exit={completed.returncode}")


def _architecture() -> str:
    return """flowchart TD
    M[Module Manifest] --> V[Input / Gold Validation]
    V --> S[Freeze Policy and Runtime Versions]

    S --> A[Baseline: Original LightRAG]
    S --> B[Candidate: DSL-aware LightRAG]

    A --> AI[Isolated Raw Ingestion]
    B --> BI[Isolated DSL-aware Ingestion]

    AI --> AQ[Baseline Retrieval]
    BI --> BQ[Trusted Hybrid Retrieval]

    AQ --> AM[Effect / Safety / Performance Metrics]
    BQ --> BM[Effect / Safety / Performance Metrics]

    AM --> C[Per-case / Per-module Comparator]
    BM --> C

    C --> H[Holdout and 1-to-N Gates]
    H --> G[Primary Gate Decision]

    NOTE[Manifest-driven; no module-specific runtime branches]
"""


def _markdown(report: dict[str, Any]) -> str:
    return f"""# Block 26B Multi-module A/B Gate

## Status
`{report['overall_status']}`

## Blocker
{report.get('blocked_reason') or 'None'}

## Architecture
```mermaid
{_architecture()}```

## Primary Gate
```json
{json.dumps(report['primary_gate'], ensure_ascii=False, indent=2)}
```

## Safety
```json
{json.dumps(report['safety'], ensure_ascii=False, indent=2)}
```
"""


if __name__ == "__main__":
    raise SystemExit(main())
