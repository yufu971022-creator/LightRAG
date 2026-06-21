from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lightrag_ext.us_dsl.scripts.run_unified_local_e2e import _cleanup, _capability_scope
from lightrag_ext.us_dsl.tests.unified_e2e_test_helpers import run


def test_us_ac_ux_and_code_agent_are_disabled(tmp_path: Path) -> None:
    safety = run(tmp_path).safety_check
    assert safety["us_generation_executed"] is False
    assert safety["ac_generation_executed"] is False
    assert safety["ux_generation_executed"] is False
    assert safety["code_agent_called"] is False


def test_no_live_or_production_connections(tmp_path: Path) -> None:
    safety = run(tmp_path).safety_check
    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_query_behavior_changed"] is False
    assert safety["production_storage_connected"] is False
    assert safety["neo4j_connected"] is False


def test_capability_scope_excludes_downstream_generation() -> None:
    scope = _capability_scope()
    assert scope["functional_qa_in_scope"] is True
    assert scope["impact_analysis_in_scope"] is True
    assert scope["us_generation_in_scope"] is False
    assert scope["ac_generation_in_scope"] is False


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


def test_result_is_serializable(tmp_path: Path) -> None:
    from lightrag_ext.us_dsl.unified_e2e_types import to_plain_dict

    json.dumps(to_plain_dict(run(tmp_path)))
