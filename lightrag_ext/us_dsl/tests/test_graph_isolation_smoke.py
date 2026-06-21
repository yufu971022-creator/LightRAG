from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import requests

from lightrag_ext.us_dsl.semantic_branch_executor import (
    cleanup_test_workspaces,
    execute_fixture_suite,
    real_embedding_allowed,
    require_real_embedding_allowed,
    workspace_inside_artifact_root,
)
from lightrag_ext.us_dsl.semantic_branch_types import SemanticBranchExecutionConfig


def _config(tmp_path: Path) -> SemanticBranchExecutionConfig:
    return SemanticBranchExecutionConfig(artifact_root=str(tmp_path))


def test_real_embedding_requires_explicit_env_flag():
    assert real_embedding_allowed({}) is False
    with pytest.raises(RuntimeError):
        require_real_embedding_allowed({})
    assert real_embedding_allowed({"LIGHTRAG_ENABLE_REAL_SEMANTIC_BRANCH_SMOKE": "1"}) is True


def test_default_tests_do_not_access_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def blocked_request(*args, **kwargs):
        raise AssertionError("network request must not be opened")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked_request)
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))

    assert suite.safety_check["real_llm_calls_executed"] is False


def test_default_tests_do_not_write_remote_storage(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))

    assert suite.safety_check["production_storage_writes_executed"] is False
    assert suite.safety_check["neo4j_connected"] is False


def test_workspace_is_inside_artifact_root(tmp_path: Path):
    assert workspace_inside_artifact_root(_config(tmp_path)) is True


def test_cleanup_removes_all_test_workspaces(tmp_path: Path):
    workspace = tmp_path / "workspaces" / "temp"
    workspace.mkdir(parents=True)
    (workspace / "file.txt").write_text("x", encoding="utf-8")

    result = cleanup_test_workspaces(str(tmp_path))

    assert result["cleanup_passed"] is True
    assert list((tmp_path / "workspaces").iterdir()) == []


def test_artifact_completeness_check(tmp_path: Path):
    import json

    from lightrag_ext.us_dsl.semantic_branch_executor import REQUIRED_ARTIFACT_FILES, validate_artifacts

    report = {
        "sidecar_alignment_passed": True,
        "endpoint_closure_passed": True,
        "forbidden_relation_count": 0,
        "duplicate_semantic_object_count": 0,
        "idempotency_passed": True,
        "issue_object_written_to_pfss_count": 0,
        "artifacts_complete": False,
        "real_embedding_smoke_status": "NOT_RUN",
    }
    for name in REQUIRED_ARTIFACT_FILES:
        path = tmp_path / name
        if name == "semantic_branch_report.json":
            path.write_text(json.dumps(report), encoding="utf-8")
        elif name.endswith(".json"):
            path.write_text("{}", encoding="utf-8")
        else:
            path.write_text("present", encoding="utf-8")

    validation = validate_artifacts(str(tmp_path))

    assert validation["artifacts_complete"] is True
    assert validation["missing_files"] == []
    assert validation["json_parse_failures"] == []


def test_real_embedding_not_run_status_is_not_run(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))
    report = suite.report()

    assert report["real_embedding_smoke_executed"] is False
    assert report["real_embedding_smoke_status"] == "NOT_RUN"
    assert report["real_embedding_smoke_passed"] is None
