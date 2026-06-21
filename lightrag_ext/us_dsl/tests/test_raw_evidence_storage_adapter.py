from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lightrag_ext.us_dsl.raw_evidence_chain import (
    RawEvidenceRouteContract,
    build_fixture_requests,
    run_idempotency_check,
)
from lightrag_ext.us_dsl.raw_evidence_storage_adapter import (
    TEXT_INDEX_STRATEGY,
    RawEvidenceIndexConfig,
    index_raw_evidence,
    snapshot_storage,
)
from lightrag_ext.us_dsl.unified_document_parser import build_unified_parse_result
from lightrag_ext.us_dsl.unified_document_types import UnifiedParseConfig


def _config(tmp_path: Path, workspace: str) -> RawEvidenceIndexConfig:
    return RawEvidenceIndexConfig(
        execution_mode="ISOLATED_WRITE",
        artifact_root=str(tmp_path),
        workspace=workspace,
        embedding_dim=8,
    )


def _parse(content: str | None = None):
    request = build_fixture_requests()[0]
    return build_unified_parse_result(
        content=content if content is not None else request.content,
        document_metadata={"document_id": request.document_id, "file_name": request.file_name, **request.metadata},
        config=UnifiedParseConfig(chunk_token_size=128),
    )


def _run_index(tmp_path: Path, workspace: str = "storage_adapter"):
    parse_result = _parse()
    config = _config(tmp_path, workspace)
    result = asyncio.run(
        index_raw_evidence(
            parse_result=parse_result,
            route_decision=RawEvidenceRouteContract(selected_plan_route="DSL_FULL"),
            config=config,
            trace_id=f"trace-{workspace}",
        )
    )
    return parse_result, result, config


def test_storage_strategy_is_selected_from_actual_capability(tmp_path: Path):
    _, result, _ = _run_index(tmp_path, "strategy")

    assert result.text_index_strategy == TEXT_INDEX_STRATEGY
    assert result.status == "TEXT_INDEXED"


def test_full_docs_are_written(tmp_path: Path):
    _, result, config = _run_index(tmp_path, "full_docs")
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert result.full_docs_written is True
    assert snapshot.full_docs_count == 1


def test_text_chunks_are_written(tmp_path: Path):
    parse_result, result, config = _run_index(tmp_path, "text_chunks")
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert result.text_chunks_written is True
    assert snapshot.text_chunks_count == len(parse_result.raw_chunks)


def test_chunk_vectors_are_written(tmp_path: Path):
    parse_result, result, config = _run_index(tmp_path, "chunk_vectors")
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert result.chunk_vectors_written is True
    assert snapshot.chunks_vdb_count == len(parse_result.raw_chunks)
    assert result.embedding_called is True
    assert result.embedding_vector_count == len(parse_result.raw_chunks)


def test_doc_status_is_written(tmp_path: Path):
    _, result, config = _run_index(tmp_path, "doc_status")
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert result.doc_status_written is True
    assert snapshot.doc_status_count == 1


def test_entities_vdb_is_not_written(tmp_path: Path):
    _, result, config = _run_index(tmp_path, "entities_vdb")
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert result.entity_vector_write_called is False
    assert snapshot.entities_vdb_count == 0


def test_relationships_vdb_is_not_written(tmp_path: Path):
    _, result, config = _run_index(tmp_path, "relationships_vdb")
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert result.relation_vector_write_called is False
    assert snapshot.relationships_vdb_count == 0


def test_graph_nodes_and_edges_are_not_written(tmp_path: Path):
    _, result, config = _run_index(tmp_path, "graph")
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert result.graph_write_called is False
    assert snapshot.graph_node_count == 0
    assert snapshot.graph_edge_count == 0


def test_extract_entities_is_not_called(tmp_path: Path):
    _, result, _ = _run_index(tmp_path, "no_extract")

    assert result.extract_entities_called is False


def test_llm_is_not_called(tmp_path: Path):
    _, result, _ = _run_index(tmp_path, "no_llm")

    assert result.llm_called is False


def test_same_document_version_is_idempotent(tmp_path: Path):
    config = _config(tmp_path, "idempotent")

    report = asyncio.run(run_idempotency_check(config=config))

    assert report.passed is True
    assert report.first_chunk_ids == report.second_chunk_ids
    assert report.after_first_snapshot == report.after_second_snapshot


def test_parse_failed_writes_no_chunks_or_vectors(tmp_path: Path):
    parse_result = _parse(content="   \n")
    config = _config(tmp_path, "parse_failed")

    result = asyncio.run(
        index_raw_evidence(
            parse_result=parse_result,
            route_decision=RawEvidenceRouteContract(selected_plan_route="PARSE_FAILED"),
            config=config,
            trace_id="trace-parse-failed",
        )
    )
    snapshot = snapshot_storage(str(Path(config.artifact_root) / "workspaces"), config.workspace)

    assert result.status == "FAILED"
    assert result.raw_chunk_count == 0
    assert snapshot.text_chunks_count == 0
    assert snapshot.chunks_vdb_count == 0
    assert snapshot.doc_status_count == 1


def test_storage_schema_matches_current_lightrag_version(tmp_path: Path):
    parse_result, _, config = _run_index(tmp_path, "schema")
    root = Path(config.artifact_root) / "workspaces" / config.workspace
    full_docs = _read_json(root / "kv_store_full_docs.json")
    text_chunks = _read_json(root / "kv_store_text_chunks.json")
    doc_status = _read_json(root / "kv_store_doc_status.json")

    full_doc = full_docs[parse_result.document.document_version_id]
    chunk = next(iter(text_chunks.values()))
    status = doc_status[parse_result.document.document_version_id]

    assert {"content", "file_path"}.issubset(full_doc)
    assert {"content", "tokens", "chunk_order_index", "full_doc_id", "llm_cache_list", "source_id"}.issubset(chunk)
    assert {"status", "content_summary", "content_length", "chunks_count", "chunks_list", "track_id"}.issubset(status)
    assert chunk["full_doc_id"] == parse_result.document.document_version_id
    assert len(status["chunks_list"]) == len(parse_result.raw_chunks)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
