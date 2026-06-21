from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import requests

from lightrag_ext.us_dsl.sidecar_persistence_service import build_sidecar_fixture_bundle, persist_sidecar_bundle
from lightrag_ext.us_dsl.sidecar_registry_types import SidecarPersistenceConfig, to_plain_dict
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository, SidecarPathError


def test_database_path_must_be_inside_artifact_root(tmp_path: Path):
    with pytest.raises(SidecarPathError):
        SQLiteSidecarRepository(str(tmp_path / "sidecar.db"), artifact_root=str(tmp_path / "artifact"))

    valid = tmp_path / "artifact" / "workspaces" / "run" / "sidecar.db"
    repo = SQLiteSidecarRepository(str(valid), artifact_root=str(tmp_path / "artifact"))
    repo.initialize_schema()
    assert valid.exists()


def test_no_secret_fields_are_persisted(tmp_path: Path):
    db = tmp_path / "artifact" / "workspaces" / "run" / "sidecar.db"
    repo = SQLiteSidecarRepository(str(db), artifact_root=str(tmp_path / "artifact"))
    repo.initialize_schema()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-public", document_id="doc-public")
    result = persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())

    dump = "\n".join(repo._conn.iterdump()).lower()
    assert result.status == "COMPLETED"
    assert "api_key" not in dump
    assert "authorization" not in dump
    assert "secret" not in dump


def test_default_tests_use_no_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def blocked_request(*args, **kwargs):
        raise AssertionError("network request must not be opened")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked_request)
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-no-network", document_id="doc-no-network")
    result = persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())

    assert result.status == "COMPLETED"


def test_default_tests_call_no_models():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-no-model", document_id="doc-no-model")
    result = persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())

    assert result.status == "COMPLETED"
    assert "llm" not in json.dumps(to_plain_dict(result)).lower()
    assert "embedding" not in json.dumps(to_plain_dict(result)).lower()


def test_default_tests_write_no_lightrag_storage(tmp_path: Path):
    artifact = tmp_path / "artifact"
    db = artifact / "workspaces" / "run" / "sidecar.db"
    repo = SQLiteSidecarRepository(str(db), artifact_root=str(artifact))
    repo.initialize_schema()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-no-lightrag-storage", document_id="doc-no-lightrag-storage")
    result = persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig(artifact_root=str(artifact)))

    files = [path.name for path in artifact.rglob("*") if path.is_file()]
    assert result.status == "COMPLETED"
    assert "sidecar.db" in files
    assert not any(name.startswith("kv_store_") or name.startswith("vdb_") for name in files)


def test_report_is_serializable():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-serializable", document_id="doc-serializable")
    result = persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())

    json.dumps(to_plain_dict(result), sort_keys=True)


def test_no_lightrag_core_modified():
    result = subprocess.run(["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], check=False, capture_output=True, text=True, timeout=30)

    assert result.stdout.strip() == ""


def test_failed_transaction_leaves_only_failed_batch():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-guard-failure", document_id="doc-guard-failure", fail_after_semantic_relations=True)
    result = persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())

    assert result.status == "FAILED"
    assert repo.count_table("ingestion_batches") == 1
    assert repo.get_batch(result.batch_id)["status"] == "FAILED"
    assert repo.count_table("documents") == 0
    assert repo.count_table("semantic_relations") == 0
    assert repo.count_table("graph_object_mappings") == 0
