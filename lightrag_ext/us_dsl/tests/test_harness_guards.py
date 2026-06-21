from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lightrag_ext.us_dsl.harness_generalization_guard import scan_harness_runtime
from lightrag_ext.us_dsl.harness_types import to_plain_dict
from lightrag_ext.us_dsl.scripts.run_three_scenario_harness_smoke import _cleanup, _safety_check
from lightrag_ext.us_dsl.tests.harness_27a_test_helpers import req_many
from lightrag_ext.us_dsl.harness_executor import run_harness


def test_no_real_embedding_or_llm_calls() -> None:
    safety = _safety_check(scan_harness_runtime(Path.cwd()).to_dict(), Path.cwd())
    assert safety["real_embedding_calls_executed"] is False
    assert safety["real_llm_calls_executed"] is False


def test_no_code_agent_call() -> None:
    safety = _safety_check(scan_harness_runtime(Path.cwd()).to_dict(), Path.cwd())
    assert safety["code_agent_called"] is False


def test_no_knowledge_storage_write() -> None:
    safety = _safety_check(scan_harness_runtime(Path.cwd()).to_dict(), Path.cwd())
    assert safety["knowledge_storage_writes_executed"] is False


def test_no_live_upload_query_or_harness_hook() -> None:
    safety = _safety_check(scan_harness_runtime(Path.cwd()).to_dict(), Path.cwd())
    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_query_behavior_changed"] is False
    assert safety["live_harness_hook_connected"] is False


def test_report_is_serializable() -> None:
    payload = to_plain_dict(run_harness(req_many(), mode="DRY_RUN"))
    json.dumps(payload, ensure_ascii=False)


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
    (workspace / "trace.txt").write_text("temporary", encoding="utf-8")
    result = _cleanup(workspaces, workspace, enabled=True)
    assert result["cleanup_passed"] is True
    assert list(workspaces.iterdir()) == []
