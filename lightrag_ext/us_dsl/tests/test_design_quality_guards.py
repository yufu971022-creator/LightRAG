from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lightrag_ext.us_dsl.design_quality_generalization_guard import scan_design_quality_runtime
from lightrag_ext.us_dsl.scripts.run_qa_impact_quality_gate import _cleanup, _safety_check


def test_no_us_or_ac_generation() -> None:
    safety = _safety_check(Path.cwd(), scan_design_quality_runtime(Path.cwd()).to_dict())
    assert safety["us_generation_executed"] is False
    assert safety["ac_generation_executed"] is False


def test_no_code_agent_call() -> None:
    safety = _safety_check(Path.cwd(), scan_design_quality_runtime(Path.cwd()).to_dict())
    assert safety["code_agent_called"] is False


def test_no_knowledge_storage_write() -> None:
    safety = _safety_check(Path.cwd(), scan_design_quality_runtime(Path.cwd()).to_dict())
    assert safety["knowledge_storage_writes_executed"] is False


def test_no_live_upload_query_harness_change() -> None:
    safety = _safety_check(Path.cwd(), scan_design_quality_runtime(Path.cwd()).to_dict())
    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_query_behavior_changed"] is False
    assert safety["live_harness_hook_connected"] is False


def test_no_lightrag_core_modified() -> None:
    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.stdout.strip() == ""


def test_cleanup_removes_workspaces(tmp_path: Path) -> None:
    workspaces = tmp_path / "workspaces"
    workspace = workspaces / "run"
    workspace.mkdir(parents=True)
    (workspace / "temp.txt").write_text("temporary", encoding="utf-8")
    result = _cleanup(workspaces, workspace, True)
    assert result["cleanup_passed"] is True
    assert list(workspaces.iterdir()) == []


def test_safety_report_is_json_serializable() -> None:
    safety = _safety_check(Path.cwd(), scan_design_quality_runtime(Path.cwd()).to_dict())
    json.dumps(safety)
