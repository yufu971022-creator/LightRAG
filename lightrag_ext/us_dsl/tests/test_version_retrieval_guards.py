from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def smoke_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_dir = tmp_path_factory.mktemp("version_aware_retrieval_smoke")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lightrag_ext.us_dsl.scripts.run_version_aware_retrieval_smoke",
            "--output-dir",
            str(output_dir),
            "--fixture-suite",
            "--all-intents",
            "--anti-hardcode-check",
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


def test_no_live_query_change(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    assert safety["live_query_behavior_changed"] is False
    assert safety["live_query_hook_connected"] is False


def test_no_real_embedding_or_llm_calls(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    assert safety["real_embedding_calls_executed"] is False
    assert safety["real_llm_calls_executed"] is False


def test_no_pfss_or_generic_graph_write(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    assert safety["pfss_graph_writes_executed"] is False
    assert safety["generic_graph_writes_executed"] is False


def test_no_production_database_or_neo4j(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    assert safety["production_database_connected"] is False
    assert safety["neo4j_connected"] is False


def test_report_is_serializable(smoke_output: Path) -> None:
    report = _load(smoke_output, "version_retrieval_report.json")
    json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert report["artifacts_complete"] is True


def test_no_lightrag_core_modified(smoke_output: Path) -> None:
    safety = _load(smoke_output, "safety_check.json")
    assert safety["lightrag_core_modified"] is False
    assert (smoke_output / "core_diff_check.txt").read_text(encoding="utf-8") == "NO_CORE_DIFF\n"


def test_cleanup_removes_workspace(smoke_output: Path) -> None:
    cleanup = _load(smoke_output, "cleanup_report.json")
    assert cleanup["cleanup_passed"] is True
    assert not (smoke_output / "workspaces" / "version_retrieval_smoke").exists()
