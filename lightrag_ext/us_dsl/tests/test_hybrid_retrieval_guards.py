from __future__ import annotations

import json
import shutil
from pathlib import Path

from lightrag_ext.us_dsl.hybrid_retrieval_types import to_plain_dict
from lightrag_ext.us_dsl.scripts.run_hybrid_retrieval_smoke import _cleanup, _safety_check


def test_no_live_query_change() -> None:
    safety = _safety_check()
    assert safety["LIVE_QUERY_BEHAVIOR_CHANGED"] is False
    assert safety["LIVE_QUERY_HOOK_CONNECTED"] is False


def test_no_real_llm_calls() -> None:
    safety = _safety_check()
    assert safety["REAL_LLM_CALLS_EXECUTED"] is False
    assert safety["FINAL_ANSWER_GENERATED"] is False


def test_no_graph_or_sidecar_write() -> None:
    safety = _safety_check()
    assert safety["PFSS_GRAPH_WRITES_EXECUTED"] is False
    assert safety["GENERIC_GRAPH_WRITES_EXECUTED"] is False
    assert safety["graph_writes_executed"] is False
    assert safety["sidecar_writes_executed"] is False


def test_no_production_storage_or_neo4j() -> None:
    safety = _safety_check()
    assert safety["PRODUCTION_STORAGE_CONNECTED"] is False
    assert safety["NEO4J_CONNECTED"] is False


def test_no_new_supersedes_created() -> None:
    safety = _safety_check()
    assert safety["NEW_SUPERSEDES_CREATED"] is False


def test_no_lightrag_core_modified() -> None:
    safety = _safety_check()
    assert safety["LIGHTRAG_CORE_MODIFIED"] is False


def test_cleanup_removes_workspaces(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    workspace = output_dir / "workspaces" / "run"
    workspace.mkdir(parents=True)
    report = _cleanup(output_dir, workspace, enabled=True)
    assert report["cleanup_passed"] is True
    assert not workspace.exists()
    shutil.rmtree(output_dir, ignore_errors=True)


def test_guard_payload_is_serializable() -> None:
    json.dumps(to_plain_dict(_safety_check()))
