from __future__ import annotations

# ruff: noqa: E402

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lightrag_ext.us_dsl.raw_evidence_chain import (
    architecture_mermaid,
    build_safety_check,
    cleanup_workspace,
    core_diff_text,
    git_status_text,
    markdown_report,
    mapping_payload,
    parse_results_payload,
    real_embedding_allowed,
    run_idempotency_check,
    run_raw_evidence_chain,
    storage_strategy_report,
)
from lightrag_ext.us_dsl.raw_evidence_storage_adapter import RawEvidenceIndexConfig
from lightrag_ext.us_dsl.unified_document_types import to_plain_dict

DEFAULT_OUTPUT_DIR = "artifacts/block_24b1_raw_evidence_chain"
DEFAULT_WORKSPACE = "block24b1_raw_evidence"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Block 24B-1 raw evidence chain smoke")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE)
    parser.add_argument("--execution-mode", choices=["PLAN_ONLY", "ISOLATED_WRITE"], default="ISOLATED_WRITE")
    parser.add_argument("--real-embedding", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "workspaces").mkdir(parents=True, exist_ok=True)
    command_log: list[str] = [
        "Block 24B-1 raw evidence chain smoke",
        f"output_dir={output_dir}",
        f"workspace={args.workspace}",
        f"execution_mode={args.execution_mode}",
        f"real_embedding_requested={args.real_embedding}",
        "network_calls_executed=false",
        "model_calls_executed=false",
    ]
    git_status_before = git_status_text()
    core_diff_before = core_diff_text()

    unresolved: list[str] = []
    if args.real_embedding and not real_embedding_allowed(dict(os.environ)):
        unresolved.append("real_embedding_smoke_blocked: LIGHTRAG_ENABLE_REAL_RAW_EVIDENCE_SMOKE=1 is required")
        command_log.append("real_embedding_blocked_by_env_gate=true")
        use_real_embedding = False
    else:
        use_real_embedding = bool(args.real_embedding)

    config = RawEvidenceIndexConfig(
        execution_mode=args.execution_mode,
        artifact_root=str(output_dir),
        workspace=args.workspace,
        use_real_embedding=use_real_embedding,
        local_storage_only=True,
    )
    run = asyncio.run(run_raw_evidence_chain(config=config))
    if unresolved:
        run = type(run)(
            protocol_version=run.protocol_version,
            artifact_root=run.artifact_root,
            workspace=run.workspace,
            execution_mode=run.execution_mode,
            results=run.results,
            storage_snapshot=run.storage_snapshot,
            safety_check=run.safety_check,
            unresolved_questions=unresolved,
            recommended_next_block=run.recommended_next_block,
        )
    idempotency = asyncio.run(run_idempotency_check(config=config))

    core_diff_after = core_diff_text()
    lightrag_core_modified = core_diff_after != "NO_CORE_DIFF"
    safety = build_safety_check(lightrag_core_modified=lightrag_core_modified)
    report = run.report()
    report["safety_check"] = safety
    report["lightrag_core_modified"] = lightrag_core_modified

    cleanup_report: dict[str, Any]
    if args.cleanup:
        cleanup_report = cleanup_workspace(str(output_dir), args.workspace)
    else:
        cleanup_report = {
            "workspace": args.workspace,
            "workspace_dir": str(output_dir / "workspaces" / args.workspace),
            "cleanup_requested": False,
            "cleanup_passed": True,
        }

    files = {
        "raw_evidence_chain_report.json": report,
        "parse_results.json": parse_results_payload(run),
        "chunk_text_unit_mapping.json": mapping_payload(run),
        "storage_strategy_report.json": storage_strategy_report(config),
        "storage_snapshot.json": to_plain_dict(run.storage_snapshot),
        "idempotency_report.json": to_plain_dict(idempotency),
        "safety_check.json": safety,
        "cleanup_report.json": cleanup_report,
    }
    for name, payload in files.items():
        _write_json(output_dir / name, payload)

    (output_dir / "ingestion_note.txt").write_text(
        "24B-1 did not call /documents/upload, insert, ainsert, ainsert_custom_kg, LLM, extract_entities, or graph writes.\n",
        encoding="utf-8",
    )
    (output_dir / "raw_evidence_chain_report.md").write_text(
        markdown_report(run, idempotency=idempotency), encoding="utf-8"
    )
    (output_dir / "architecture.mmd").write_text(architecture_mermaid(), encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text(_unresolved_markdown(unresolved), encoding="utf-8")
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    (output_dir / "git_status_before.txt").write_text(git_status_before + "\n", encoding="utf-8")
    (output_dir / "git_status_after.txt").write_text(git_status_text() + "\n", encoding="utf-8")
    (output_dir / "core_diff_check.txt").write_text(
        f"before:\n{core_diff_before}\n\nafter:\n{core_diff_after}\n", encoding="utf-8"
    )
    return 0


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _unresolved_markdown(unresolved: list[str]) -> str:
    if not unresolved:
        return "# Unresolved Questions\n\n- None for this isolated smoke scope.\n"
    rows = ["# Unresolved Questions", ""]
    rows.extend(f"- {item}" for item in unresolved)
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
