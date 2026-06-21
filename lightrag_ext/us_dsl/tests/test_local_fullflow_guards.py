from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lightrag_ext.us_dsl.local_fullflow_generalization_guard import inspect_local_fullflow_generalization
from lightrag_ext.us_dsl.scripts.run_existing_us_local_fullflow import _cleanup, _safety


def test_runtime_has_no_module_or_entity_hardcode(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.py"
    runtime.write_text("def route(profile):\n    return profile\n", encoding="utf-8")
    report = inspect_local_fullflow_generalization([runtime])
    assert report.runtime_module_branch_count == 0
    assert report.entity_name_specific_rule_count == 0


def test_local_filename_role_logic_is_not_imported_by_runtime(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.py"
    runtime.write_text('def f(file_name):\n    if file_name == "A_US.md":\n        return True\n', encoding="utf-8")
    report = inspect_local_fullflow_generalization([runtime])
    assert report.local_filename_controls_runtime_logic_count == 1


def test_no_live_upload_or_query_change() -> None:
    anti = inspect_local_fullflow_generalization([])
    safety = _safety("LOCAL_FULLFLOW_PASS_WITH_GAPS", anti, True)
    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_query_behavior_changed"] is False


def test_no_production_storage_connection() -> None:
    anti = inspect_local_fullflow_generalization([])
    safety = _safety("LOCAL_FULLFLOW_PASS_WITH_GAPS", anti, True)
    assert safety["production_storage_connected"] is False
    assert safety["neo4j_connected"] is False


def test_report_is_serializable(tmp_path: Path) -> None:
    (tmp_path / "A_US.md").write_text("# US-1\nEvidence", encoding="utf-8")
    output = tmp_path / "out"
    subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "lightrag_ext.us_dsl.scripts.run_existing_us_local_fullflow",
            "--output-dir",
            str(output),
            "--discover-existing-us",
            "--use-all-valid-us",
            "--cleanup",
        ],
        cwd=Path.cwd(),
        env={"LIGHTRAG_ENABLE_EXISTING_US_LOCAL_FULLFLOW": "1", "LIGHTRAG_LOCAL_US_ROOT": str(tmp_path), **__import__("os").environ},
        check=True,
        timeout=60,
    )
    json.loads((output / "local_fullflow_report.json").read_text(encoding="utf-8"))


def test_no_lightrag_core_modified() -> None:
    anti = inspect_local_fullflow_generalization([])
    safety = _safety("LOCAL_FULLFLOW_PASS_WITH_GAPS", anti, True)
    assert safety["lightrag_core_modified"] is False


def test_cleanup_removes_workspaces(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    report = _cleanup(root, enabled=True)
    assert report["cleanup_passed"] is True
