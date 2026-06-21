from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lightrag_ext.us_dsl.scripts.run_multi_module_ab_gate import _cleanup, _safety_check


def test_workspaces_are_isolated(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    baseline = root / "module-a" / "baseline_workspace"
    candidate = root / "module-a" / "candidate_workspace"
    baseline.mkdir(parents=True)
    candidate.mkdir(parents=True)
    assert baseline != candidate


def test_no_production_storage_connection() -> None:
    safety = _safety_check("BLOCKED_INPUT_SET", {})
    assert safety["production_storage_connected"] is False
    assert safety["neo4j_connected"] is False


def test_no_live_upload_or_query_hook() -> None:
    safety = _safety_check("BLOCKED_INPUT_SET", {})
    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_query_behavior_changed"] is False
    assert safety["live_upload_hook_connected"] is False
    assert safety["live_query_hook_connected"] is False


def test_reports_redact_secrets(tmp_path: Path) -> None:
    output = tmp_path / "out"
    subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "lightrag_ext.us_dsl.scripts.run_multi_module_ab_gate",
            "--manifest",
            "<<MODULE_MANIFEST_PATH>>",
            "--output-dir",
            str(output),
            "--cleanup",
        ],
        cwd=Path.cwd(),
        check=True,
        timeout=60,
    )
    payload = (output / "multi_module_ab_report.json").read_text(encoding="utf-8").casefold()
    assert "api_key" not in payload
    assert "authorization" not in payload
    assert "token" not in payload


def test_report_is_serializable(tmp_path: Path) -> None:
    output = tmp_path / "out"
    subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "lightrag_ext.us_dsl.scripts.run_multi_module_ab_gate",
            "--output-dir",
            str(output),
            "--cleanup",
        ],
        cwd=Path.cwd(),
        check=True,
        timeout=60,
    )
    json.loads((output / "multi_module_ab_report.json").read_text(encoding="utf-8"))


def test_no_lightrag_core_modified() -> None:
    safety = _safety_check("BLOCKED_INPUT_SET", {})
    assert safety["lightrag_core_modified"] is False


def test_cleanup_removes_all_workspaces(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    (root / "run").mkdir(parents=True)
    report = _cleanup(root, enabled=True)
    assert report["cleanup_passed"] is True
    assert report["remaining_entries"] == []
