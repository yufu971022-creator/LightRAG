from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.unified_ingestion_protocol import (
    DslAwareIngestionOrchestrator,
    UnifiedIngestionRequest,
    safety_invariants,
    serialize_plan,
    serialize_protocol_report,
)


ARTIFACT_DIR = Path("artifacts/block_24b0_shadow_router")
FORBIDDEN_CORE_PATHS = [
    "lightrag/lightrag.py",
    "lightrag/operate.py",
    "lightrag/prompt.py",
    "lightrag/api",
]


def main() -> int:
    repo = _repo_root()
    artifact_dir = repo / ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _write_text(artifact_dir / "git_status_before.txt", _git_status(repo))
    plans = build_sample_shadow_route_plans()
    protocol_report = serialize_protocol_report(plans)
    protocol_report.update(
        {
            "repository_path": str(repo),
            "generated_at": _now(),
            "git_commit": _git(repo, "rev-parse", "HEAD"),
            "current_branch": _git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
            "live_upload_behavior_changed": False,
            "live_shadow_hook_connected": False,
            "auto_write_routing_enabled": False,
        }
    )
    _write_json(artifact_dir / "unified_ingestion_protocol_report.json", protocol_report)
    _write_json(
        artifact_dir / "shadow_route_plans.json",
        {"plans": [serialize_plan(plan) for plan in plans]},
    )
    _write_json(artifact_dir / "safety_invariants.json", safety_invariants())
    _write_text(artifact_dir / "unified_ingestion_protocol_report.md", _render_markdown(protocol_report))
    _write_text(artifact_dir / "core_diff_check.txt", _core_diff_check(repo))
    _append_command_log(artifact_dir / "command_log.txt")
    _write_text(artifact_dir / "git_status_after.txt", _git_status(repo))
    print(f"REPORT={artifact_dir / 'unified_ingestion_protocol_report.json'}")
    return 0


def build_sample_shadow_route_plans() -> list:
    orchestrator = DslAwareIngestionOrchestrator()
    requests = [
        UnifiedIngestionRequest(
            document_id="24b0-dsl-full",
            file_name="synthetic_product_design_full.md",
            mode="shadow",
            metadata={"domain": "MasterData"},
            content=(
                "# User Story US-2401\n"
                "Domain: MasterData\n"
                "Feature: Bank Status Reference Data\n"
                "Source: US-2401 text unit TU-1 evidence.\n"
                "Acceptance Criteria:\n"
                "Given Query Condition contains account lifecycle inputs.\n"
                "When the customer account is active and KYC is complete.\n"
                "Then Bank Status is set to Eligible.\n"
                "Business Rule: Bank Status is determined by Query Condition.\n"
                "Entity: Bank Status. Entity: Query Condition. Relationship: Bank Status SupportedByEvidence Query Condition.\n"
                "Evidence: US-2401 TU-1 contains the exact source span for both entities.\n"
            ),
        ),
        UnifiedIngestionRequest(
            document_id="24b0-domain-only",
            file_name="synthetic_domain_only.txt",
            mode="auto",
            metadata={"domain": "MasterData"},
            content="MasterData is mentioned here, but this note has no user story, evidence, object definitions, or acceptance criteria.",
        ),
        UnifiedIngestionRequest(
            document_id="24b0-version-risk",
            file_name="synthetic_version_partial.md",
            mode="dsl",
            metadata={"domain": "RuleManagement"},
            allow_generic_graph_fallback=True,
            content=(
                "User Story US-2402\n"
                "Domain: RuleManagement\n"
                "Business Rule: Fee Rule Version v2 supersedes v1.\n"
                "Acceptance Criteria: Then Fee Rule Version is used for calculation.\n"
                "Evidence: US-2402 TU-3 states that the supersedes relationship needs reviewer approval.\n"
                "Type: TBD for legacy override object.\n"
            ),
        ),
        UnifiedIngestionRequest(
            document_id="24b0-raw-only",
            file_name="synthetic_raw_note.txt",
            mode="raw",
            content="A short operational note without DSL structure. It should keep raw text only in this planning round.",
        ),
        UnifiedIngestionRequest(
            document_id="24b0-parse-failed",
            file_name="empty.txt",
            mode="shadow",
            content="   ",
        ),
    ]
    return [orchestrator.build_plan(request) for request in requests]


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Block 24B-0 Unified Ingestion Protocol Report",
        "",
        "## Safety Invariants",
        "",
        "```text",
        *[f"{key} = {str(value).lower()}" for key, value in report["safety_invariants"].items()],
        "```",
        "",
        "## Protocol Summary",
        "",
        f"- Protocol version: `{report['protocol_version']}`",
        f"- Plan count: `{report['plan_count']}`",
        f"- Route distribution: `{report['route_distribution']}`",
        "- Live upload behavior changed: `false`",
        "- Live shadow hook connected: `false`",
        "- Auto write routing enabled: `false`",
        "",
        "## Decision Model",
        "",
        "```mermaid",
        "flowchart TD",
        "  R[UnifiedIngestionRequest] --> P[Document Semantic Profile]",
        "  P --> M[DSL Applicability Metrics]",
        "  M --> D{Shadow Route Decision}",
        "  D --> F[DSL_FULL]",
        "  D --> A[DSL_PARTIAL]",
        "  D --> O[RAW_ONLY]",
        "  D --> X[PARSE_FAILED]",
        "  D -. plan only .-> N[No write APIs called]",
        "```",
        "",
        "## Plans",
        "",
        "| Document | Mode | Live Route | Shadow Candidate | Selected Plan | Score | Risks | Notes |",
        "| --- | --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for plan in report["plans"]:
        metrics = plan["metrics"]
        notes = "; ".join(plan["notes"])
        lines.append(
            "| {doc} | `{mode}` | `{live}` | `{shadow}` | `{selected}` | {score} | {risks} | {notes} |".format(
                doc=plan["request"]["document_id"],
                mode=plan["requested_mode"],
                live=plan["live_route"],
                shadow=plan["shadow_candidate_route"],
                selected=plan["selected_plan_route"],
                score=metrics["score"],
                risks=metrics["object_risk_count"],
                notes=_escape_table(notes),
            )
        )
    lines.extend(
        [
            "",
            "## Current Boundary",
            "",
            "- `/documents/upload` is not modified or connected in 24B-0.",
            "- `insert`, `ainsert`, and `ainsert_custom_kg` are not called by this planner.",
            "- Domain hit alone is insufficient for DSL_FULL; structure, evidence, object signals, and risk counts are required.",
            "- Generic Graph fallback is only represented as a disabled/enabled plan field; no native graph extraction runs.",
            "",
        ]
    )
    return "\n".join(lines)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=False, capture_output=True, text=True)
    return result.stdout.strip() or "unresolved"


def _git_status(repo: Path) -> str:
    result = subprocess.run(["git", "status", "--short", "--branch"], cwd=repo, check=False, capture_output=True, text=True)
    return result.stdout


def _core_diff_check(repo: Path) -> str:
    result = subprocess.run(["git", "diff", "--", *FORBIDDEN_CORE_PATHS], cwd=repo, check=False, capture_output=True, text=True)
    if result.stdout.strip():
        return result.stdout
    return "No diff in forbidden core/API files for Block 24B-0.\n"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _append_command_log(path: Path) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write("Block 24B-0 commands executed:\n")
        file.write(".venv/bin/python -m lightrag_ext.us_dsl.scripts.run_24b0_shadow_router_report\n")
        file.write("git diff -- lightrag/lightrag.py lightrag/operate.py lightrag/prompt.py lightrag/api\n")


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
