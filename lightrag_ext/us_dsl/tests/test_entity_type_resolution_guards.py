from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def smoke_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_dir = tmp_path_factory.mktemp("entity_type_resolution_guards")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lightrag_ext.us_dsl.scripts.run_entity_type_resolution_smoke",
            "--output-dir",
            str(output_dir),
            "--fixture-suite",
            "--fake-deterministic-embedding",
            "--isolated-pfss-smoke",
            "--cleanup",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return output_dir


def _load(output_dir: Path, name: str) -> dict[str, object]:
    return json.loads((output_dir / name).read_text(encoding="utf-8"))


def test_no_real_embedding_or_llm_calls(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    assert safety["real_embedding_calls_executed"] is False
    assert safety["real_llm_calls_executed"] is False


def test_no_live_upload_or_query_change(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_query_behavior_changed"] is False
    assert safety["live_upload_hook_connected"] is False
    assert safety["auto_write_routing_enabled"] is False


def test_no_production_database_or_neo4j(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    assert safety["production_database_connected"] is False
    assert safety["neo4j_connected"] is False
    assert safety["production_graph_rewrite_executed"] is False


def test_report_is_serializable(smoke_output: Path) -> None:
    report = _load(smoke_output, "entity_type_resolution_report.json")
    json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert report["artifacts_complete"] is True


def test_no_lightrag_core_modified(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    core_diff = (smoke_output / "core_diff_check.txt").read_text(encoding="utf-8")
    assert safety["lightrag_core_modified"] is False
    assert core_diff == "NO_CORE_DIFF\n"


def test_cleanup_removes_all_workspaces(smoke_output: Path) -> None:
    cleanup = _load(smoke_output, "cleanup_report.json")
    assert cleanup["cleanup_passed"] is True
    assert not (smoke_output / "workspaces" / "block25a1_smoke").exists()
