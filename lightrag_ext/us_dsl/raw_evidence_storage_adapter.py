from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from lightrag.base import DocStatus
from lightrag.kg.json_doc_status_impl import JsonDocStatusStorage
from lightrag.kg.json_kv_impl import JsonKVStorage
from lightrag.kg.nano_vector_db_impl import NanoVectorDBStorage
from lightrag.kg.shared_storage import initialize_pipeline_status, initialize_share_data
from lightrag.namespace import NameSpace
from lightrag.utils import EmbeddingFunc, get_content_summary

from .unified_document_parser import DSL_CONTEXT_FORBIDDEN_TERMS
from .unified_document_types import UnifiedParseResult


TEXT_INDEX_STRATEGY = "DIRECT_STORAGE_ADAPTER"


@dataclass(frozen=True)
class RawEvidenceIndexConfig:
    enabled: bool = True
    execution_mode: Literal["PLAN_ONLY", "ISOLATED_WRITE"] = "PLAN_ONLY"
    use_real_embedding: bool = False
    local_storage_only: bool = True
    cleanup_after_run: bool = False
    artifact_root: str = "artifacts/block_24b1_raw_evidence_chain"
    workspace: str = "block24b1_raw_evidence"
    namespace: str = "raw_evidence"
    timeout_seconds: int = 120
    enforce_single_parse: bool = True
    enforce_no_llm: bool = True
    enforce_no_graph_write: bool = True
    embedding_dim: int = 8


@dataclass(frozen=True)
class RawEvidenceStorageSnapshot:
    full_docs_count: int = 0
    text_chunks_count: int = 0
    chunks_vdb_count: int = 0
    doc_status_count: int = 0
    graph_node_count: int = 0
    graph_edge_count: int = 0
    entities_vdb_count: int = 0
    relationships_vdb_count: int = 0


@dataclass(frozen=True)
class RawEvidenceIndexResult:
    trace_id: str
    document_id: str
    document_version_id: str
    semantic_route: str
    text_index_strategy: str
    parser_call_count: int
    source_text_unit_count: int
    raw_chunk_count: int
    mapping_link_count: int
    raw_chunk_coverage: float
    text_unit_coverage: float
    orphan_chunk_count: int
    orphan_text_unit_count: int
    full_docs_written: bool
    text_chunks_written: bool
    chunk_vectors_written: bool
    doc_status_written: bool
    embedding_called: bool
    embedding_vector_count: int
    embedding_dimension: int | None
    llm_called: bool
    extract_entities_called: bool
    graph_write_called: bool
    entity_vector_write_called: bool
    relation_vector_write_called: bool
    dsl_context_contamination_count: int
    idempotency_key_count: int
    idempotency_passed: bool
    storage_snapshot_before: RawEvidenceStorageSnapshot
    storage_snapshot_after: RawEvidenceStorageSnapshot
    status: str
    issues: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


class CountingEmbedding:
    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.call_count = 0
        self.vector_count = 0

    async def __call__(self, texts: list[str]) -> np.ndarray:
        self.call_count += 1
        self.vector_count += len(texts)
        rows = []
        for text in texts:
            seed = sum(ord(char) for char in text) % 997
            rows.append([((seed + index) % 101) / 100.0 for index in range(self.dim)])
        return np.array(rows, dtype=np.float32)


def make_counting_embedding_func(dim: int = 8) -> tuple[EmbeddingFunc, CountingEmbedding]:
    counter = CountingEmbedding(dim)
    return (
        EmbeddingFunc(
            embedding_dim=dim,
            max_token_size=8192,
            func=counter,
            model_name=f"block24b1-counting-{dim}d",
        ),
        counter,
    )


async def index_raw_evidence(
    *,
    rag: Any = None,
    parse_result: UnifiedParseResult,
    route_decision: Any,
    config: RawEvidenceIndexConfig,
    embedding_func: EmbeddingFunc | None = None,
    trace_id: str = "block24b1-trace",
) -> RawEvidenceIndexResult:
    del rag
    route = _route_name(route_decision)
    issues = list(parse_result.issues)
    if route != "PARSE_FAILED" and not _raw_text_required(route_decision):
        issues.append("router_contract_violation_raw_text_required_false")
        return _result_without_write(parse_result, route, config, trace_id, issues, status="ROUTER_CONTRACT_VIOLATION")
    if not config.enabled or config.execution_mode == "PLAN_ONLY":
        return _result_without_write(parse_result, route, config, trace_id, issues, status="PLANNED")
    workspace_dir = Path(config.artifact_root) / "workspaces"
    working_dir = workspace_dir.resolve()
    working_dir.mkdir(parents=True, exist_ok=True)
    if not str(working_dir).endswith("workspaces"):
        issues.append("unsafe_workspace_root")
        return _result_without_write(parse_result, route, config, trace_id, issues, status="FAILED")
    embedding_func, counter = _embedding_with_counter(config, embedding_func)
    stores = await _init_stores(working_dir, config.workspace, embedding_func)
    before = snapshot_storage(str(working_dir), config.workspace)
    if route == "PARSE_FAILED" or not parse_result.raw_chunks:
        await _write_failed_status(stores["doc_status"], parse_result, trace_id, route, issues)
        await stores["doc_status"].index_done_callback()
        after = snapshot_storage(str(working_dir), config.workspace)
        return _build_result(parse_result, route, config, trace_id, before, after, counter, False, False, True, issues, "FAILED")
    contamination = dsl_context_contamination_count(parse_result)
    if contamination:
        issues.append("dsl_context_contamination_detected")
    await stores["full_docs"].upsert(_full_docs_payload(parse_result))
    await stores["text_chunks"].upsert(_text_chunks_payload(parse_result))
    await stores["chunks_vdb"].upsert(_text_chunks_payload(parse_result))
    await stores["doc_status"].upsert(_doc_status_payload(parse_result, trace_id, route))
    for store in stores.values():
        await store.index_done_callback()
    after = snapshot_storage(str(working_dir), config.workspace)
    return _build_result(parse_result, route, config, trace_id, before, after, counter, True, True, True, issues, "TEXT_INDEXED")


def snapshot_storage(working_dir: str, workspace: str) -> RawEvidenceStorageSnapshot:
    root = Path(working_dir) / workspace
    return RawEvidenceStorageSnapshot(
        full_docs_count=_kv_count(root / "kv_store_full_docs.json"),
        text_chunks_count=_kv_count(root / "kv_store_text_chunks.json"),
        chunks_vdb_count=_vdb_count(root / "vdb_chunks.json"),
        doc_status_count=_kv_count(root / "kv_store_doc_status.json"),
        graph_node_count=_graph_counts(root)[0],
        graph_edge_count=_graph_counts(root)[1],
        entities_vdb_count=_vdb_count(root / "vdb_entities.json"),
        relationships_vdb_count=_vdb_count(root / "vdb_relationships.json"),
    )


def dsl_context_contamination_count(parse_result: UnifiedParseResult) -> int:
    return sum(
        1
        for chunk in parse_result.raw_chunks
        if any(term in chunk.content for term in DSL_CONTEXT_FORBIDDEN_TERMS)
    )


async def _init_stores(working_dir: Path, workspace: str, embedding_func: EmbeddingFunc) -> dict[str, Any]:
    global_config = {
        "working_dir": str(working_dir),
        "embedding_batch_num": 10,
        "embedding_func": embedding_func,
        "vector_db_storage_cls_kwargs": {"cosine_better_than_threshold": 0.2},
    }
    initialize_share_data(workers=1)
    await initialize_pipeline_status(workspace=workspace)
    stores = {
        "full_docs": JsonKVStorage(namespace=NameSpace.KV_STORE_FULL_DOCS, workspace=workspace, global_config=global_config, embedding_func=embedding_func),
        "text_chunks": JsonKVStorage(namespace=NameSpace.KV_STORE_TEXT_CHUNKS, workspace=workspace, global_config=global_config, embedding_func=embedding_func),
        "chunks_vdb": NanoVectorDBStorage(namespace=NameSpace.VECTOR_STORE_CHUNKS, workspace=workspace, global_config=global_config, embedding_func=embedding_func, meta_fields={"full_doc_id", "content", "file_path"}),
        "doc_status": JsonDocStatusStorage(namespace=NameSpace.DOC_STATUS, workspace=workspace, global_config=global_config, embedding_func=None),
    }
    for store in stores.values():
        await store.initialize()
    return stores


def _full_docs_payload(parse_result: UnifiedParseResult) -> dict[str, dict[str, Any]]:
    doc = parse_result.document
    return {doc.document_version_id: {"content": doc.normalized_text, "file_path": doc.file_name or doc.source_path or "inline_document"}}


def _text_chunks_payload(parse_result: UnifiedParseResult) -> dict[str, dict[str, Any]]:
    doc = parse_result.document
    return {
        chunk.chunk_id: {
            "content": chunk.content,
            "tokens": chunk.token_count,
            "chunk_order_index": chunk.chunk_order,
            "full_doc_id": doc.document_version_id,
            "file_path": doc.file_name or doc.source_path or "inline_document",
            "llm_cache_list": [],
            "source_id": doc.document_version_id,
            "status": "preprocessed",
            "metadata": {
                "document_id": doc.document_id,
                "document_version_id": doc.document_version_id,
                "source_span": chunk.source_span,
                "content_hash": chunk.content_hash,
            },
        }
        for chunk in parse_result.raw_chunks
    }


def _doc_status_payload(parse_result: UnifiedParseResult, trace_id: str, route: str) -> dict[str, dict[str, Any]]:
    doc = parse_result.document
    return {
        doc.document_version_id: {
            "status": DocStatus.PREPROCESSED,
            "content_summary": get_content_summary(doc.normalized_text),
            "content_length": len(doc.normalized_text),
            "chunks_count": len(parse_result.raw_chunks),
            "chunks_list": [chunk.chunk_id for chunk in parse_result.raw_chunks],
            "created_at": doc.parse_started_at,
            "updated_at": doc.parse_finished_at,
            "file_path": doc.file_name or doc.source_path or "inline_document",
            "track_id": trace_id,
            "metadata": {
                "raw_evidence_status": "TEXT_INDEXED",
                "semantic_route": route,
                "document_id": doc.document_id,
                "document_version_id": doc.document_version_id,
            },
        }
    }


async def _write_failed_status(doc_status, parse_result: UnifiedParseResult, trace_id: str, route: str, issues: list[str]) -> None:
    doc = parse_result.document
    await doc_status.upsert(
        {
            doc.document_version_id: {
                "status": DocStatus.FAILED,
                "content_summary": get_content_summary(doc.normalized_text),
                "content_length": len(doc.normalized_text),
                "chunks_count": 0,
                "chunks_list": [],
                "created_at": doc.parse_started_at,
                "updated_at": doc.parse_finished_at,
                "file_path": doc.file_name or doc.source_path or "inline_document",
                "track_id": trace_id,
                "error_msg": ";".join(issues) or "parse_failed",
                "metadata": {"raw_evidence_status": "FAILED", "semantic_route": route},
            }
        }
    )


def _embedding_with_counter(config: RawEvidenceIndexConfig, embedding_func: EmbeddingFunc | None) -> tuple[EmbeddingFunc, Any]:
    if embedding_func is None:
        return make_counting_embedding_func(config.embedding_dim)
    counter = getattr(embedding_func.func, "__self__", None)
    if counter is None or not hasattr(counter, "vector_count"):
        counter = type("EmbeddingCounterView", (), {"call_count": 0, "vector_count": 0, "dim": embedding_func.embedding_dim})()
    return embedding_func, counter


def _build_result(
    parse_result: UnifiedParseResult,
    route: str,
    config: RawEvidenceIndexConfig,
    trace_id: str,
    before: RawEvidenceStorageSnapshot,
    after: RawEvidenceStorageSnapshot,
    counter: Any,
    full_docs_written: bool,
    text_chunks_written: bool,
    doc_status_written: bool,
    issues: list[str],
    status: str,
) -> RawEvidenceIndexResult:
    vectors_written = after.chunks_vdb_count >= len(parse_result.raw_chunks) and bool(parse_result.raw_chunks)
    return RawEvidenceIndexResult(
        trace_id=trace_id,
        document_id=parse_result.document.document_id,
        document_version_id=parse_result.document.document_version_id,
        semantic_route=route,
        text_index_strategy=TEXT_INDEX_STRATEGY,
        parser_call_count=parse_result.parser_call_count,
        source_text_unit_count=len(parse_result.source_text_units),
        raw_chunk_count=len(parse_result.raw_chunks),
        mapping_link_count=len(parse_result.chunk_text_unit_links),
        raw_chunk_coverage=parse_result.raw_chunk_coverage,
        text_unit_coverage=parse_result.text_unit_coverage,
        orphan_chunk_count=parse_result.orphan_chunk_count,
        orphan_text_unit_count=parse_result.orphan_text_unit_count,
        full_docs_written=full_docs_written,
        text_chunks_written=text_chunks_written,
        chunk_vectors_written=vectors_written,
        doc_status_written=doc_status_written,
        embedding_called=getattr(counter, "call_count", 0) > 0,
        embedding_vector_count=getattr(counter, "vector_count", 0),
        embedding_dimension=getattr(counter, "dim", config.embedding_dim),
        llm_called=False,
        extract_entities_called=False,
        graph_write_called=False,
        entity_vector_write_called=False,
        relation_vector_write_called=False,
        dsl_context_contamination_count=dsl_context_contamination_count(parse_result),
        idempotency_key_count=len({parse_result.document.document_version_id, *[chunk.chunk_id for chunk in parse_result.raw_chunks]}),
        idempotency_passed=after.text_chunks_count <= before.text_chunks_count + len(parse_result.raw_chunks),
        storage_snapshot_before=before,
        storage_snapshot_after=after,
        status=status,
        issues=issues,
        risks=[] if config.local_storage_only else ["non_local_storage_requested"],
    )


def _result_without_write(parse_result: UnifiedParseResult, route: str, config: RawEvidenceIndexConfig, trace_id: str, issues: list[str], status: str) -> RawEvidenceIndexResult:
    snapshot = RawEvidenceStorageSnapshot()
    return _build_result(parse_result, route, config, trace_id, snapshot, snapshot, type("Counter", (), {"call_count": 0, "vector_count": 0, "dim": config.embedding_dim})(), False, False, False, issues, status)


def _route_name(route_decision: Any) -> str:
    if isinstance(route_decision, str):
        return route_decision
    return str(getattr(route_decision, "recommended_future_route", None) or getattr(route_decision, "selected_plan_route", None) or getattr(route_decision, "semantic_route", None) or route_decision)


def _raw_text_required(route_decision: Any) -> bool:
    if isinstance(route_decision, str):
        return route_decision in {"DSL_FULL", "DSL_PARTIAL", "RAW_ONLY"}
    return bool(getattr(route_decision, "raw_text_required", True))


def _kv_count(path: Path) -> int:
    data = _read_json(path)
    return len(data) if isinstance(data, dict) else 0


def _vdb_count(path: Path) -> int:
    data = _read_json(path)
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return len(data["data"])
    if isinstance(data, dict) and isinstance(data.get("storage"), dict):
        return len(data["storage"])
    return 0


def _graph_counts(root: Path) -> tuple[int, int]:
    graph_files = list(root.glob("graph_*.graphml"))
    if not graph_files:
        return 0, 0
    try:
        import networkx as nx

        graph = nx.read_graphml(graph_files[0])
        return graph.number_of_nodes(), graph.number_of_edges()
    except Exception:
        return 0, 0


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
