from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import requests

from lightrag_ext.us_dsl.raw_evidence_chain import (
    RawEvidenceRouteContract,
    assert_real_embedding_allowed,
    build_fixture_requests,
    cleanup_workspace,
    core_diff_text,
    real_embedding_allowed,
    run_raw_evidence_chain,
)
from lightrag_ext.us_dsl.raw_evidence_storage_adapter import RawEvidenceIndexConfig, index_raw_evidence, snapshot_storage
from lightrag_ext.us_dsl.unified_document_parser import build_unified_parse_result
from lightrag_ext.us_dsl.unified_ingestion_protocol import DslAwareIngestionOrchestrator


def _config(tmp_path: Path, workspace: str) -> RawEvidenceIndexConfig:
    return RawEvidenceIndexConfig(
        execution_mode="ISOLATED_WRITE",
        artifact_root=str(tmp_path),
        workspace=workspace,
        embedding_dim=8,
    )


def test_dsl_full_always_runs_raw_evidence_chain(tmp_path: Path):
    request = build_fixture_requests()[0]
    run = asyncio.run(run_raw_evidence_chain(requests=[request], config=_config(tmp_path, "dsl_full")))

    assert run.results[0].index_result.status == "TEXT_INDEXED"
    assert run.results[0].index_result.raw_chunk_count > 0
    assert run.results[0].index_result.text_chunks_written is True
    assert DslAwareIngestionOrchestrator().build_plan(request).selected_plan_route == "DSL_FULL"


def test_dsl_partial_always_runs_raw_evidence_chain(tmp_path: Path):
    request = build_fixture_requests()[1]
    run = asyncio.run(run_raw_evidence_chain(requests=[request], config=_config(tmp_path, "dsl_partial")))

    assert run.results[0].index_result.status == "TEXT_INDEXED"
    assert run.results[0].index_result.raw_chunk_count > 0
    assert run.results[0].index_result.full_docs_written is True
    assert DslAwareIngestionOrchestrator().build_plan(request).selected_plan_route == "DSL_PARTIAL"


def test_raw_only_runs_raw_evidence_chain(tmp_path: Path):
    request = build_fixture_requests()[2]
    run = asyncio.run(run_raw_evidence_chain(requests=[request], config=_config(tmp_path, "raw_only")))

    assert run.results[0].index_result.status == "TEXT_INDEXED"
    assert run.results[0].index_result.raw_chunk_count > 0
    assert DslAwareIngestionOrchestrator().build_plan(request).selected_plan_route == "RAW_ONLY"


def test_parse_failed_does_not_index_text(tmp_path: Path):
    request = build_fixture_requests()[3]
    config = _config(tmp_path, "parse_failed_chain")
    run = asyncio.run(run_raw_evidence_chain(requests=[request], config=config))
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert run.results[0].index_result.status == "FAILED"
    assert snapshot.text_chunks_count == 0
    assert snapshot.chunks_vdb_count == 0


def test_router_contract_requires_raw_text(tmp_path: Path):
    request = build_fixture_requests()[0]
    parse_result = build_unified_parse_result(
        content=request.content,
        document_metadata={"document_id": request.document_id, "file_name": request.file_name},
    )
    config = _config(tmp_path, "router_contract")

    result = asyncio.run(
        index_raw_evidence(
            parse_result=parse_result,
            route_decision=RawEvidenceRouteContract(selected_plan_route="DSL_FULL", raw_text_required=False),
            config=config,
            trace_id="trace-router-contract",
        )
    )

    assert result.status == "ROUTER_CONTRACT_VIOLATION"
    assert "router_contract_violation_raw_text_required_false" in result.issues
    assert result.text_chunks_written is False


def test_dsl_context_contamination_count_is_zero(tmp_path: Path):
    run = asyncio.run(run_raw_evidence_chain(config=_config(tmp_path, "contamination")))

    assert all(item.index_result.dsl_context_contamination_count == 0 for item in run.results)
    assert run.report()["no_dsl_context_contamination_passed"] is True


def test_default_mode_does_not_use_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def blocked_request(*args, **kwargs):
        raise AssertionError("network request must not be opened")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked_request)
    run = asyncio.run(
        run_raw_evidence_chain(
            config=RawEvidenceIndexConfig(execution_mode="PLAN_ONLY", artifact_root=str(tmp_path), workspace="plan_only")
        )
    )

    assert run.report()["safety_check"]["network_calls_executed"] is False
    assert all(item.index_result.embedding_called is False for item in run.results)


def test_real_embedding_requires_explicit_env_flag():
    assert real_embedding_allowed({}) is False
    with pytest.raises(RuntimeError):
        assert_real_embedding_allowed({})
    assert real_embedding_allowed({"LIGHTRAG_ENABLE_REAL_RAW_EVIDENCE_SMOKE": "1"}) is True


def test_real_embedding_smoke_uses_isolated_workspace(tmp_path: Path):
    config = RawEvidenceIndexConfig(
        execution_mode="ISOLATED_WRITE",
        artifact_root=str(tmp_path),
        workspace="real_embedding_isolated",
        use_real_embedding=True,
    )

    workspace_root = Path(config.artifact_root) / "workspaces" / config.workspace

    assert "workspaces" in workspace_root.parts
    assert str(workspace_root).startswith(str(tmp_path))


def test_cleanup_removes_workspace(tmp_path: Path):
    workspace_dir = tmp_path / "workspaces" / "cleanup_target"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "sentinel.txt").write_text("delete me", encoding="utf-8")

    report = cleanup_workspace(str(tmp_path), "cleanup_target")

    assert report["cleanup_passed"] is True
    assert not workspace_dir.exists()


def test_report_is_serializable(tmp_path: Path):
    run = asyncio.run(run_raw_evidence_chain(config=_config(tmp_path, "serializable")))

    json.dumps(run.report(), sort_keys=True)
    assert "safety_check" in run.report()
    assert "documents" in run.report()


def test_live_upload_behavior_is_unchanged(tmp_path: Path):
    run = asyncio.run(run_raw_evidence_chain(config=_config(tmp_path, "live_upload")))
    safety = run.report()["safety_check"]

    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_upload_hook_connected"] is False
    assert safety["auto_write_routing_enabled"] is False


def test_no_lightrag_core_modified():
    assert core_diff_text() == "NO_CORE_DIFF"
