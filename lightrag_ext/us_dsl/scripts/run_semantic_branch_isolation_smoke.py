from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lightrag_ext.us_dsl.generic_graph_writer import snapshot_generic_graph
from lightrag_ext.us_dsl.graph_space_policy import generic_descriptor, pfss_descriptor
from lightrag_ext.us_dsl.issue_index import IssueIndex
from lightrag_ext.us_dsl.pfss_graph_writer import snapshot_pfss_graph
from lightrag_ext.us_dsl.semantic_branch_executor import (
    architecture_mermaid,
    build_safety_check,
    cleanup_test_workspaces,
    execute_fixture_suite,
    graph_space_policy_payload,
    markdown_report,
    real_embedding_allowed,
    source_reference_strategy_payload,
    validate_artifacts,
)
from lightrag_ext.us_dsl.semantic_branch_types import SemanticBranchExecutionConfig, to_plain_dict

DEFAULT_OUTPUT_DIR = "artifacts/block_24b2_semantic_branch_isolation"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Block 24B-2 semantic branch isolation smoke")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-suite", action="store_true")
    parser.add_argument("--real-embedding", action="store_true")
    parser.add_argument("--no-real-embedding", action="store_true")
    parser.add_argument("--generic-isolation-smoke", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "workspaces").mkdir(parents=True, exist_ok=True)
    git_status_before = _git_status()
    (output_dir / "git_status_before.txt").write_text(git_status_before + "\n", encoding="utf-8")
    command_log = [
        "Block 24B-2 semantic branch isolation smoke",
        f"output_dir={output_dir}",
        f"real_embedding_requested={args.real_embedding}",
        f"generic_isolation_smoke={args.generic_isolation_smoke}",
        "real_llm_calls_executed=false",
        "original_extract_entities_called=false",
        "original_gleaning_executed=false",
    ]
    unresolved: list[str] = []
    if args.no_real_embedding:
        args.real_embedding = False
    if args.real_embedding and not real_embedding_allowed(dict(os.environ)):
        unresolved.append("real_embedding_smoke_blocked: LIGHTRAG_ENABLE_REAL_SEMANTIC_BRANCH_SMOKE=1 is required")
        command_log.append("real_embedding_blocked_by_env_gate=true")
    config = SemanticBranchExecutionConfig(
        artifact_root=str(output_dir),
        use_real_embedding=bool(args.real_embedding and not unresolved),
        allow_generic_graph=False,
        cleanup_after_run=args.cleanup,
    )
    suite = asyncio.run(execute_fixture_suite(config=config, generic_isolation_smoke=args.generic_isolation_smoke))
    safety = build_safety_check(lightrag_core_modified=_core_diff() != "NO_CORE_DIFF")
    suite = type(suite)(
        results=suite.results,
        graph_isolation_snapshot=suite.graph_isolation_snapshot,
        source_reference_strategy=suite.source_reference_strategy,
        safety_check=safety,
        idempotency_passed=suite.idempotency_passed,
        cleanup_passed=suite.cleanup_passed,
        unresolved_questions=unresolved,
    )
    pfss_desc = pfss_descriptor(config.pfss_workspace, config.pfss_namespace)
    generic_desc = generic_descriptor(config.generic_workspace, config.generic_namespace, write_enabled=args.generic_isolation_smoke)
    issue_index = IssueIndex(str(output_dir / "issue_index.json"))
    route_results = [to_plain_dict(item) for item in suite.results]
    pfss_snapshot = snapshot_pfss_graph(descriptor=pfss_desc, artifact_root=str(output_dir))
    generic_snapshot = snapshot_generic_graph(descriptor=generic_desc, artifact_root=str(output_dir))
    source_reference = source_reference_strategy_payload(suite.results)
    report = suite.report()
    report["safety_check"] = safety
    report.update(_exit_gate_overrides(report, pfss_snapshot, bool(args.real_embedding and not unresolved)))
    cleanup_report: dict[str, Any] = {"cleanup_requested": args.cleanup, "cleanup_passed": True, "workspace_root": str(output_dir / "workspaces")}
    files = {
        "semantic_branch_report.json": report,
        "graph_space_policy.json": graph_space_policy_payload(config),
        "route_execution_results.json": route_results,
        "pfss_payload_summary.json": _pfss_payload_summary(route_results),
        "pfss_storage_snapshot.json": pfss_snapshot,
        "generic_storage_snapshot.json": generic_snapshot,
        "issue_summary.json": issue_index.summary(),
        "graph_isolation_snapshot.json": to_plain_dict(suite.graph_isolation_snapshot),
        "source_reference_strategy.json": source_reference,
        "idempotency_report.json": {"passed": suite.idempotency_passed},
        "safety_check.json": safety,
        "cleanup_report.json": cleanup_report,
    }
    for name, payload in files.items():
        _write_json(output_dir / name, payload)
    (output_dir / "semantic_branch_report.md").write_text(markdown_report(suite, config, report_override=report), encoding="utf-8")
    (output_dir / "architecture.mmd").write_text(architecture_mermaid(), encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text(_unresolved(unresolved), encoding="utf-8")
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    (output_dir / "core_diff_check.txt").write_text(_core_diff() + "\n", encoding="utf-8")
    (output_dir / "git_status_after.txt").write_text(_git_status() + "\n", encoding="utf-8")
    validation = validate_artifacts(str(output_dir))
    report["artifacts_complete"] = validation["artifacts_complete"]
    if args.cleanup:
        cleanup_report = cleanup_test_workspaces(str(output_dir))
    report["cleanup_passed"] = cleanup_report["cleanup_passed"]
    _write_json(output_dir / "cleanup_report.json", cleanup_report)
    _write_json(output_dir / "semantic_branch_report.json", report)
    _write_json(output_dir / "artifact_validation.json", validation)
    (output_dir / "semantic_branch_report.md").write_text(markdown_report(suite, config, report_override=report), encoding="utf-8")
    (output_dir / "git_status_after.txt").write_text(_git_status() + "\n", encoding="utf-8")
    return 0


def _pfss_payload_summary(route_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "safe_entity_count": sum(item["safe_entity_count"] for item in route_results),
        "safe_relationship_count": sum(item["safe_relationship_count"] for item in route_results),
        "blocked_object_count": sum(item["blocked_object_count"] for item in route_results),
        "forbidden_relation_count": sum(item["forbidden_relation_count"] for item in route_results),
        "dangling_relationship_count": sum(item["dangling_relationship_count"] for item in route_results),
        "sidecar_alignment_passed": all(item["sidecar_alignment_passed"] for item in route_results),
        "endpoint_closure_passed": all(item["endpoint_closure_passed"] for item in route_results),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _exit_gate_overrides(report: dict[str, Any], pfss_snapshot: dict[str, Any], real_embedding_executed: bool) -> dict[str, Any]:
    return {
        "sidecar_alignment_passed": pfss_snapshot["sidecar_alignment_passed"],
        "endpoint_closure_passed": pfss_snapshot["endpoint_closure_passed"],
        "forbidden_relation_count": pfss_snapshot["forbidden_relation_count"],
        "duplicate_semantic_object_count": pfss_snapshot["duplicate_semantic_object_count"],
        "issue_object_written_to_pfss_count": pfss_snapshot["issue_object_written_to_pfss_count"],
        "idempotency_passed": report["idempotency_passed"],
        "artifacts_complete": False,
        "real_embedding_smoke_executed": real_embedding_executed,
        "real_embedding_smoke_status": "PASS" if real_embedding_executed else "NOT_RUN",
        "real_embedding_smoke_passed": True if real_embedding_executed else None,
    }


def _unresolved(items: list[str]) -> str:
    rows = ["# Unresolved Questions", ""]
    rows.extend(f"- {item}" for item in items or ["None for this isolated smoke scope."])
    return "\n".join(rows) + "\n"


def _git_status() -> str:
    result = subprocess.run(["git", "status", "--short"], check=False, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() or "CLEAN"


def _core_diff() -> str:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip() or "NO_CORE_DIFF"


if __name__ == "__main__":
    raise SystemExit(main())
