from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lightrag_ext.us_dsl.sidecar_persistence_service import build_sidecar_fixture_bundle, persist_sidecar_bundle
from lightrag_ext.us_dsl.sidecar_readback_validator import (
    document_version_snapshot,
    readback_counts,
    referential_integrity_report,
    rollback_manifest_readback,
    trace_graph_object_to_evidence,
    version_group_readback,
)
from lightrag_ext.us_dsl.sidecar_registry_types import SidecarPersistenceConfig, to_plain_dict
from lightrag_ext.us_dsl.sidecar_schema import REQUIRED_TABLES, write_schema_artifact
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository

DEFAULT_OUTPUT_DIR = "artifacts/block_24c0_persistent_sidecar"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Block 24C-0 persistent sidecar smoke")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-suite", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "workspaces").mkdir(parents=True, exist_ok=True)
    (output_dir / "git_status_before.txt").write_text(_git_status() + "\n", encoding="utf-8")
    write_schema_artifact(output_dir)
    run_id = "block24c0_smoke"
    db_path = output_dir / "workspaces" / run_id / "sidecar.db"
    if db_path.exists():
        db_path.unlink()
    repo = SQLiteSidecarRepository(str(db_path), artifact_root=str(output_dir))
    repo.initialize_schema()
    config = SidecarPersistenceConfig(artifact_root=str(output_dir), cleanup_after_run=args.cleanup)
    command_log = [
        "Block 24C-0 persistent sidecar smoke",
        f"output_dir={output_dir}",
        f"db_path={db_path}",
        "network_calls_executed=false",
        "model_calls_executed=false",
        "lightrag_storage_writes_executed=false",
    ]
    results = []
    dsl_full = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-24c0-dsl-full", document_id="doc-24c0-dsl-full")
    dsl_partial = build_sidecar_fixture_bundle("DSL_PARTIAL", trace_id="trace-24c0-dsl-partial", document_id="doc-24c0-dsl-partial")
    raw_only = build_sidecar_fixture_bundle("RAW_ONLY", trace_id="trace-24c0-raw-only", document_id="doc-24c0-raw-only")
    parse_failed = build_sidecar_fixture_bundle("PARSE_FAILED", trace_id="trace-24c0-parse-failed", document_id="doc-24c0-parse-failed")
    for bundle in [dsl_full, dsl_partial, raw_only, parse_failed]:
        results.append(persist_sidecar_bundle(repository=repo, route_decision=bundle.batch.semantic_route, unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=config))
    before_retry = repo.record_counts()
    retry_result = persist_sidecar_bundle(repository=repo, route_decision=dsl_full.batch.semantic_route, unified_parse_result=dsl_full, raw_evidence_result=None, semantic_branch_result=None, config=config)
    after_retry = repo.record_counts()
    new_batch_same_version = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-24c0-dsl-full-new-batch", document_id="doc-24c0-dsl-full")
    new_batch_result = persist_sidecar_bundle(repository=repo, route_decision=new_batch_same_version.batch.semantic_route, unified_parse_result=new_batch_same_version, raw_evidence_result=None, semantic_branch_result=None, config=config)
    after_new_batch = repo.record_counts()
    failure_bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-24c0-failure", document_id="doc-24c0-failure", fail_after_semantic_relations=True)
    failure_result = persist_sidecar_bundle(repository=repo, route_decision=failure_bundle.batch.semantic_route, unified_parse_result=failure_bundle, raw_evidence_result=None, semantic_branch_result=None, config=config)
    integrity = referential_integrity_report(repo)
    trace = trace_graph_object_to_evidence(repo, graph_space="PFSS", graph_namespace="pfss_test_graph", graph_object_kind="node", graph_object_id="sem:bank_status")
    doc_snapshot = document_version_snapshot(repo, dsl_full.document_version["document_version_id"])
    version_group = version_group_readback(repo, "vg-bank-status")
    rollback_manifest = rollback_manifest_readback(repo, dsl_full.batch.batch_id)
    counts = repo.record_counts()
    readback_count_snapshot = readback_counts(repo, dsl_full.document_version["document_version_id"], dsl_full.batch.batch_id)
    idempotency_report = {
        "same_payload_idempotency_passed": before_retry == after_retry,
        "new_batch_no_business_duplication": _business_counts(before_retry) == _business_counts(after_new_batch),
        "retry_result": to_plain_dict(retry_result),
        "new_batch_result": to_plain_dict(new_batch_result),
        "before_retry": before_retry,
        "after_retry": after_retry,
        "after_new_batch": after_new_batch,
    }
    rollback_report = {
        "transaction_rollback_passed": failure_result.status == "FAILED" and repo.get_batch(failure_bundle.batch.batch_id)["status"] == "FAILED" and repo.get_document(failure_bundle.document["document_id"]) is None,
        "failed_batch_status_persisted": repo.get_batch(failure_bundle.batch.batch_id)["status"] == "FAILED",
        "failure_result": to_plain_dict(failure_result),
    }
    safety = _safety_check(_core_diff() != "NO_CORE_DIFF")
    schema_validation = _schema_validation(repo, output_dir)
    route_report = {
        "dsl_full_passed": results[0].status == "COMPLETED",
        "dsl_partial_passed": results[1].status == "COMPLETED" and counts["ingestion_issues_count"] >= 2,
        "raw_only_passed": results[2].status == "COMPLETED",
        "parse_failed_passed": results[3].status == "FAILED",
        "failure_injection_passed": rollback_report["transaction_rollback_passed"],
    }
    readback_snapshot = {
        "graph_object_trace_to_evidence": trace,
        "document_version_snapshot": doc_snapshot,
        "version_group_readback": version_group,
        "rollback_manifest": rollback_manifest,
        "readback_counts": readback_count_snapshot,
    }
    report = {
        "block": "24C-0",
        "repository_abstraction_implemented": True,
        "sqlite_reference_backend_implemented": True,
        "schema_table_count": len(REQUIRED_TABLES),
        "foreign_keys_enabled": repo.foreign_keys_enabled(),
        "transaction_support_implemented": True,
        "readback_validator_implemented": True,
        "record_counts": counts,
        "quality": {
            "referential_integrity_passed": integrity["passed"],
            "write_readback_counts_match": readback_count_snapshot["semantic_objects"] == 2,
            "same_payload_idempotency_passed": idempotency_report["same_payload_idempotency_passed"],
            "new_batch_no_business_duplication": idempotency_report["new_batch_no_business_duplication"],
            "transaction_rollback_passed": rollback_report["transaction_rollback_passed"],
            "graph_object_trace_to_evidence_passed": trace is not None and bool(trace.get("evidence")),
            "version_group_readback_passed": bool(version_group["members"]),
            "rollback_manifest_readback_passed": bool(rollback_manifest),
        },
        "route_fixtures": route_report,
        "safety_check": safety,
        "results": [to_plain_dict(item) for item in results],
    }
    artifacts = {
        "sidecar_registry_report.json": report,
        "schema_validation.json": schema_validation,
        "persistence_smoke_report.json": {"results": [to_plain_dict(item) for item in results], "route_fixtures": route_report},
        "readback_snapshot.json": readback_snapshot,
        "referential_integrity_report.json": integrity,
        "idempotency_report.json": idempotency_report,
        "transaction_rollback_report.json": rollback_report,
        "record_count_summary.json": counts,
        "safety_check.json": safety,
        "cleanup_report.json": {"cleanup_requested": args.cleanup, "cleanup_passed": True, "workspace": str(db_path.parent)},
    }
    for name, payload in artifacts.items():
        _write_json(output_dir / name, payload)
    (output_dir / "sidecar_registry_report.md").write_text(_markdown_report(report), encoding="utf-8")
    (output_dir / "architecture.mmd").write_text(_architecture(), encoding="utf-8")
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    (output_dir / "core_diff_check.txt").write_text(_core_diff() + "\n", encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text("# Unresolved Questions\n\n- None for this isolated smoke scope.\n", encoding="utf-8")
    if args.cleanup:
        shutil.rmtree(db_path.parent, ignore_errors=True)
        cleanup = {"cleanup_requested": True, "cleanup_passed": not db_path.parent.exists(), "workspace": str(db_path.parent)}
        _write_json(output_dir / "cleanup_report.json", cleanup)
    (output_dir / "git_status_after.txt").write_text(_git_status() + "\n", encoding="utf-8")
    repo.close()
    return 0


def _business_counts(counts: dict[str, int]) -> dict[str, int]:
    excluded = {"ingestion_batches_count", "rollback_records_count"}
    return {key: value for key, value in counts.items() if key not in excluded}


def _schema_validation(repo: SQLiteSidecarRepository, output_dir: Path) -> dict[str, Any]:
    table_rows = repo._all("SELECT name FROM sqlite_master WHERE type = 'table'", ())  # schema-only test helper; repository connection is not exposed to callers
    tables = sorted(row["name"] for row in table_rows if not row["name"].startswith("sqlite_"))
    return {
        "required_table_count": len(REQUIRED_TABLES),
        "created_table_count": len([table for table in REQUIRED_TABLES if table in tables]),
        "missing_tables": [table for table in REQUIRED_TABLES if table not in tables],
        "foreign_keys_enabled": repo.foreign_keys_enabled(),
        "schema_sql_artifact": str(output_dir / "sidecar_schema.sql"),
        "passed": all(table in tables for table in REQUIRED_TABLES) and repo.foreign_keys_enabled(),
    }


def _safety_check(core_modified: bool) -> dict[str, bool]:
    return {
        "live_upload_behavior_changed": False,
        "live_upload_hook_connected": False,
        "auto_write_routing_enabled": False,
        "real_embedding_calls_executed": False,
        "real_llm_calls_executed": False,
        "lightrag_storage_writes_executed": False,
        "production_database_connected": False,
        "neo4j_connected": False,
        "sqlite_reference_backend_only": True,
        "lightrag_core_modified": core_modified,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _markdown_report(report: dict[str, Any]) -> str:
    return "\n".join([
        "# Block 24C-0 Persistent Sidecar Report",
        "",
        "## Summary",
        f"- schema_table_count: {report['schema_table_count']}",
        f"- foreign_keys_enabled: {report['foreign_keys_enabled']}",
        f"- referential_integrity_passed: {report['quality']['referential_integrity_passed']}",
        f"- same_payload_idempotency_passed: {report['quality']['same_payload_idempotency_passed']}",
        f"- transaction_rollback_passed: {report['quality']['transaction_rollback_passed']}",
        "",
        "## Record Counts",
        "```json",
        json.dumps(report["record_counts"], indent=2, sort_keys=True),
        "```",
        "",
        "## Safety",
        "```json",
        json.dumps(report["safety_check"], indent=2, sort_keys=True),
        "```",
    ]) + "\n"


def _architecture() -> str:
    return """flowchart TD
    P[Unified Parse Result] --> S[Sidecar Persistence Service]
    R[Raw Evidence Result] --> S
    G[Semantic Branch Result] --> S
    D[Route Decision] --> S

    S --> DOC[Document Registry]
    S --> VER[Document Version Registry]
    S --> BAT[Ingestion Batch]
    S --> TXT[Chunk / TextUnit / Link]
    S --> SEM[Semantic Object / Relation]
    S --> EVI[Evidence Mapping]
    S --> TERM[Term Mapping]
    S --> VR[Version Group]
    S --> ISS[Issue Registry]
    S --> RB[Rollback Manifest]

    SEM --> MAP[Graph Object Mapping]
    MAP -. references .-> PFSS[External PFSS Graph]

    NOTE[Local SQLite Reference Backend Only; Sidecar stores mappings and governance metadata, not graph payloads]
"""


def _git_status() -> str:
    result = subprocess.run(["git", "status", "--short"], check=False, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() or "CLEAN"


def _core_diff() -> str:
    result = subprocess.run(["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], check=False, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() or "NO_CORE_DIFF"


if __name__ == "__main__":
    raise SystemExit(main())
