from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .payload_types import DslAwareIngestionPayload
from .storage_mapping import (
    LightRagChunkCandidate,
    build_lightrag_chunk_candidates,
    vector_content_contaminated,
)
from .test_namespace_storage import (
    FakeEmbeddingRecorder,
    build_test_namespace_storages,
    namespace_is_safe,
)


ENABLE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_REAL_STORAGE_DRY_RUN"
MAX_CHUNKS_ENV = "LIGHTRAG_DSL_REAL_STORAGE_TEST_MAX_CHUNKS"
KEEP_TEST_DATA_ENV = "LIGHTRAG_DSL_REAL_STORAGE_KEEP_TEST_DATA"
PREFERRED_SECTIONS = (
    "field_table",
    "state_rule",
    "task_rule",
    "api_desc",
    "report_rule",
    "migration_rule",
    "business_rule",
)
SYNTHETIC_MARKERS = (
    "<DSL_CONTEXT>",
    "</DSL_CONTEXT>",
    "<SOURCE_TEXT>",
    "</SOURCE_TEXT>",
)


@dataclass(frozen=True)
class RealStorageWriteDryRunConfig:
    enabled: bool = False
    dry_run: bool = True
    test_namespace_only: bool = True
    write_text_chunks: bool = True
    write_chunks_vdb: bool = True
    write_graph: bool = False
    write_full_docs: bool = False
    write_doc_status: bool = False
    call_extract_entities: bool = False
    call_merge_nodes_and_edges: bool = False
    use_fake_embedding: bool = True
    max_chunks: int = 6
    hard_max_chunks: int = 10
    cleanup_after_run: bool = True
    rollback_after_run: bool = True
    require_quality_gate_not_fail: bool = True
    allow_quality_gate_warn: bool = True
    feature_flag_name: str = "enable_dsl_aware_real_storage_dry_run"
    workspace: str | None = None
    text_chunks_namespace: str | None = None
    chunks_vdb_namespace: str | None = None

    @classmethod
    def from_env(cls) -> "RealStorageWriteDryRunConfig":
        keep_data = os.getenv(KEEP_TEST_DATA_ENV) == "1"
        return cls(
            enabled=os.getenv(ENABLE_ENV) == "1",
            max_chunks=_env_int(MAX_CHUNKS_ENV, 6),
            cleanup_after_run=not keep_data,
            rollback_after_run=not keep_data,
        )


@dataclass(frozen=True)
class RealStorageWriteItemResult:
    chunk_id: str
    content_preview: str
    section_type: str
    domain_code: str | None
    feature_key: str | None
    text_chunks_written: bool
    chunks_vdb_written: bool
    text_chunks_deleted: bool
    chunks_vdb_deleted: bool
    embedding_input_safe: bool
    metadata_ok: bool
    error: str | None = None


@dataclass
class RealStorageWriteDryRunReport:
    enabled: bool
    skipped: bool
    skip_reason: str | None
    document_id: str
    workspace: str
    working_dir: str
    text_chunks_namespace: str
    chunks_vdb_namespace: str
    text_chunks_storage_type: str
    chunks_vdb_storage_type: str
    selected_chunk_count: int
    text_chunks_written_count: int
    chunks_vdb_written_count: int
    text_chunks_deleted_count: int
    chunks_vdb_deleted_count: int
    embedding_called: bool
    embedding_call_count: int
    embedded_text_count: int
    embedding_input_contamination_count: int
    embedding_input_previews: list[str]
    vector_content_contamination_count: int
    metadata_missing_count: int
    text_chunks_metadata_retained_count: int
    chunks_vdb_metadata_retained_count: int
    idempotency_passed: bool
    rollback_passed: bool
    cleanup_passed: bool
    graph_written: bool
    extract_entities_called: bool
    merge_called: bool
    full_docs_written: bool
    doc_status_written: bool
    real_text_chunks_written: bool
    real_chunks_vdb_written: bool
    recommended_next_step: str
    risks: list[str] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    item_results: list[RealStorageWriteItemResult] = field(default_factory=list)


def run_real_storage_write_dry_run(
    payload: DslAwareIngestionPayload,
    *,
    config: RealStorageWriteDryRunConfig | None = None,
    working_dir: str | Path | None = None,
) -> RealStorageWriteDryRunReport:
    return asyncio.run(
        arun_real_storage_write_dry_run(
            payload,
            config=config,
            working_dir=working_dir,
        )
    )


async def arun_real_storage_write_dry_run(
    payload: DslAwareIngestionPayload,
    *,
    config: RealStorageWriteDryRunConfig | None = None,
    working_dir: str | Path | None = None,
) -> RealStorageWriteDryRunReport:
    config = config or RealStorageWriteDryRunConfig()
    names = _test_names(config)
    working_dir_path = Path(working_dir) if working_dir else (
        Path(tempfile.gettempdir())
        / f"lightrag_dsl_storage_test_{uuid.uuid4().hex[:10]}"
    )
    if not config.enabled:
        return _skipped_report(
            payload,
            names,
            working_dir_path,
            "Feature flag enable_dsl_aware_real_storage_dry_run is disabled.",
        )
    if _quality_gate_status(payload) == "FAIL" and config.require_quality_gate_not_fail:
        return _blocked_report(
            payload,
            names,
            working_dir_path,
            code="QUALITY_GATE_FAIL",
            message="Payload qualityGate.status is FAIL.",
        )
    if config.test_namespace_only and not namespace_is_safe(
        names["workspace"],
        names["text_chunks_namespace"],
        names["chunks_vdb_namespace"],
    ):
        return _blocked_report(
            payload,
            names,
            working_dir_path,
            code="PRODUCTION_NAMESPACE_BLOCKED",
            message="Workspace and namespaces must contain test/dsl_test.",
        )
    if not config.use_fake_embedding:
        return _blocked_report(
            payload,
            names,
            working_dir_path,
            code="REAL_EMBEDDING_BLOCKED",
            message="Only fake deterministic embedding is allowed in Block 12.",
        )

    risks: list[str] = []
    all_candidates = build_lightrag_chunk_candidates(payload)
    contamination_count = sum(
        1 for candidate in all_candidates if vector_content_contaminated(candidate.content)
    )
    candidates = _select_candidates(all_candidates, config, risks)
    metadata_missing_count = sum(1 for candidate in candidates if _metadata_missing(candidate))
    if contamination_count:
        return _blocked_report(
            payload,
            names,
            working_dir_path,
            code="VECTOR_CONTENT_CONTAMINATED",
            message="Selected vector content contains synthetic DSL markers.",
            vector_content_contamination_count=contamination_count,
            metadata_missing_count=metadata_missing_count,
        )

    embedding_recorder = FakeEmbeddingRecorder()
    cleanup_passed = False
    rollback_passed = False
    text_storage_type = "JsonKVStorage"
    vector_storage_type = ""
    vector_risk = None
    item_results: list[RealStorageWriteItemResult] = []
    try:
        text_chunks, chunks_vdb, text_storage_type, vector_storage_type, vector_risk = (
            build_test_namespace_storages(
                working_dir=working_dir_path,
                workspace=names["workspace"],
                text_chunks_namespace=names["text_chunks_namespace"],
                chunks_vdb_namespace=names["chunks_vdb_namespace"],
                embedding_recorder=embedding_recorder,
            )
        )
        if vector_risk:
            risks.append(vector_risk)
        await text_chunks.initialize()
        await chunks_vdb.initialize()

        chunk_data = {
            candidate.chunk_id: candidate.to_lightrag_chunk_value()
            for candidate in candidates
        }
        if config.write_text_chunks:
            await text_chunks.upsert(chunk_data)
            await text_chunks.index_done_callback()
        if config.write_chunks_vdb:
            await chunks_vdb.upsert(chunk_data)
            await chunks_vdb.index_done_callback()

        text_written = await _count_present(text_chunks, list(chunk_data))
        vdb_written = await _count_present(chunks_vdb, list(chunk_data))
        text_metadata_retained = await _count_metadata_retained(
            text_chunks,
            list(chunk_data),
        )
        vdb_metadata_retained = await _count_metadata_retained(
            chunks_vdb,
            list(chunk_data),
        )

        # Idempotency check: same keys should overwrite, not increase stored count.
        if config.write_text_chunks:
            await text_chunks.upsert(chunk_data)
        if config.write_chunks_vdb:
            await chunks_vdb.upsert(chunk_data)
        text_count_after_second = await _count_present(text_chunks, list(chunk_data))
        vdb_count_after_second = await _count_present(chunks_vdb, list(chunk_data))
        idempotency_passed = (
            text_count_after_second == text_written
            and vdb_count_after_second == vdb_written
        )

        text_deleted = 0
        vdb_deleted = 0
        if config.rollback_after_run:
            keys = list(chunk_data)
            await text_chunks.delete(keys)
            await chunks_vdb.delete(keys)
            await text_chunks.index_done_callback()
            await chunks_vdb.index_done_callback()
            text_deleted = text_written - await _count_present(text_chunks, keys)
            vdb_deleted = vdb_written - await _count_present(chunks_vdb, keys)
            rollback_passed = text_deleted == text_written and vdb_deleted == vdb_written

        item_results = [
            RealStorageWriteItemResult(
                chunk_id=candidate.chunk_id,
                content_preview=_preview(candidate.content),
                section_type=candidate.section_type,
                domain_code=candidate.domain_code,
                feature_key=candidate.feature_key,
                text_chunks_written=candidate.chunk_id in chunk_data,
                chunks_vdb_written=candidate.chunk_id in chunk_data,
                text_chunks_deleted=config.rollback_after_run,
                chunks_vdb_deleted=config.rollback_after_run,
                embedding_input_safe=not any(marker in candidate.content for marker in SYNTHETIC_MARKERS),
                metadata_ok=not _metadata_missing(candidate),
            )
            for candidate in candidates
        ]
        cleanup_passed = _cleanup(working_dir_path, config, risks)
        return RealStorageWriteDryRunReport(
            enabled=True,
            skipped=False,
            skip_reason=None,
            document_id=payload.document_id,
            workspace=names["workspace"],
            working_dir=str(working_dir_path),
            text_chunks_namespace=names["text_chunks_namespace"],
            chunks_vdb_namespace=names["chunks_vdb_namespace"],
            text_chunks_storage_type=text_storage_type,
            chunks_vdb_storage_type=vector_storage_type,
            selected_chunk_count=len(candidates),
            text_chunks_written_count=text_written,
            chunks_vdb_written_count=vdb_written,
            text_chunks_deleted_count=text_deleted,
            chunks_vdb_deleted_count=vdb_deleted,
            embedding_called=embedding_recorder.call_count > 0,
            embedding_call_count=embedding_recorder.call_count,
            embedded_text_count=embedding_recorder.embedded_text_count,
            embedding_input_contamination_count=sum(
                1
                for content in embedding_recorder.inputs
                if vector_content_contaminated(content)
            ),
            embedding_input_previews=[
                _preview(content) for content in embedding_recorder.inputs[:10]
            ],
            vector_content_contamination_count=contamination_count,
            metadata_missing_count=metadata_missing_count,
            text_chunks_metadata_retained_count=text_metadata_retained,
            chunks_vdb_metadata_retained_count=vdb_metadata_retained,
            idempotency_passed=idempotency_passed,
            rollback_passed=rollback_passed,
            cleanup_passed=cleanup_passed,
            graph_written=False,
            extract_entities_called=False,
            merge_called=False,
            full_docs_written=False,
            doc_status_written=False,
            real_text_chunks_written=text_written > 0,
            real_chunks_vdb_written=vdb_written > 0,
            recommended_next_step="CONSIDER_CANDIDATE_EXTRACTION_WRITE_DRY_RUN_DESIGN",
            risks=risks,
            item_results=item_results,
        )
    except Exception as exc:
        cleanup_passed = _cleanup(working_dir_path, config, risks)
        return _error_report(
            payload,
            names,
            working_dir_path,
            text_storage_type=text_storage_type,
            vector_storage_type=vector_storage_type or "unsupported",
            message=f"{exc.__class__.__name__}: {exc}",
            cleanup_passed=cleanup_passed,
            risks=risks,
        )


def serialize_real_storage_write_dry_run_report(
    report: RealStorageWriteDryRunReport,
) -> dict[str, Any]:
    return {
        "enabled": report.enabled,
        "skipped": report.skipped,
        "skipReason": report.skip_reason,
        "documentId": report.document_id,
        "workspace": report.workspace,
        "workingDir": report.working_dir,
        "textChunksNamespace": report.text_chunks_namespace,
        "chunksVdbNamespace": report.chunks_vdb_namespace,
        "textChunksStorageType": report.text_chunks_storage_type,
        "chunksVdbStorageType": report.chunks_vdb_storage_type,
        "selectedChunkCount": report.selected_chunk_count,
        "textChunksWrittenCount": report.text_chunks_written_count,
        "chunksVdbWrittenCount": report.chunks_vdb_written_count,
        "textChunksDeletedCount": report.text_chunks_deleted_count,
        "chunksVdbDeletedCount": report.chunks_vdb_deleted_count,
        "embeddingCalled": report.embedding_called,
        "embeddingCallCount": report.embedding_call_count,
        "embeddedTextCount": report.embedded_text_count,
        "embeddingInputContaminationCount": report.embedding_input_contamination_count,
        "embeddingInputPreviews": report.embedding_input_previews,
        "vectorContentContaminationCount": report.vector_content_contamination_count,
        "metadataMissingCount": report.metadata_missing_count,
        "textChunksMetadataRetainedCount": report.text_chunks_metadata_retained_count,
        "chunksVdbMetadataRetainedCount": report.chunks_vdb_metadata_retained_count,
        "idempotencyPassed": report.idempotency_passed,
        "rollbackPassed": report.rollback_passed,
        "cleanupPassed": report.cleanup_passed,
        "graphWritten": report.graph_written,
        "extractEntitiesCalled": report.extract_entities_called,
        "mergeCalled": report.merge_called,
        "fullDocsWritten": report.full_docs_written,
        "docStatusWritten": report.doc_status_written,
        "realTextChunksWritten": report.real_text_chunks_written,
        "realChunksVdbWritten": report.real_chunks_vdb_written,
        "recommendedNextStep": report.recommended_next_step,
        "risks": report.risks,
        "issues": report.issues,
        "itemResults": [asdict(item) for item in report.item_results],
    }


def _select_candidates(
    candidates: list[LightRagChunkCandidate],
    config: RealStorageWriteDryRunConfig,
    risks: list[str],
) -> list[LightRagChunkCandidate]:
    if config.max_chunks > config.hard_max_chunks:
        risks.append(
            f"max_chunks capped from {config.max_chunks} to {config.hard_max_chunks}."
        )
    limit = min(config.max_chunks, config.hard_max_chunks)
    ordered = sorted(candidates, key=_candidate_sort_key)
    return ordered[:limit]


def _candidate_sort_key(candidate: LightRagChunkCandidate):
    section_rank = (
        PREFERRED_SECTIONS.index(candidate.section_type)
        if candidate.section_type in PREFERRED_SECTIONS
        else len(PREFERRED_SECTIONS)
    )
    return section_rank, candidate.chunk_order_index, candidate.chunk_id


def _test_names(config: RealStorageWriteDryRunConfig) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    return {
        "workspace": config.workspace or f"dsl_test_workspace_{suffix}",
        "text_chunks_namespace": config.text_chunks_namespace
        or f"dsl_test_{suffix}_text_chunks",
        "chunks_vdb_namespace": config.chunks_vdb_namespace
        or f"dsl_test_{suffix}_chunks",
    }


async def _count_present(storage, keys: list[str]) -> int:
    values = await storage.get_by_ids(keys)
    return sum(1 for value in values if value)


async def _count_metadata_retained(storage, keys: list[str]) -> int:
    values = await storage.get_by_ids(keys)
    return sum(
        1
        for value in values
        if isinstance(value, dict) and isinstance(value.get("metadata"), dict)
    )


def _metadata_missing(candidate: LightRagChunkCandidate) -> bool:
    return any(
        value in (None, "", {})
        for value in (
            candidate.chunk_id,
            candidate.content,
            candidate.full_doc_id,
            candidate.source_text_unit_id,
            candidate.section_type,
            candidate.text_hash,
            candidate.source_span,
        )
    )


def _quality_gate_status(payload: DslAwareIngestionPayload) -> str:
    quality_gate = payload.summary.get("qualityGate")
    if isinstance(quality_gate, dict):
        status = quality_gate.get("status")
        if isinstance(status, str):
            return status
    return ""


def _skipped_report(
    payload: DslAwareIngestionPayload,
    names: dict[str, str],
    working_dir: Path,
    reason: str,
) -> RealStorageWriteDryRunReport:
    return _base_report(
        payload,
        names,
        working_dir,
        skipped=True,
        skip_reason=reason,
        recommended_next_step="ENABLE_FEATURE_FLAG_TO_RUN_REAL_STORAGE_DRY_RUN",
    )


def _blocked_report(
    payload: DslAwareIngestionPayload,
    names: dict[str, str],
    working_dir: Path,
    *,
    code: str,
    message: str,
    vector_content_contamination_count: int = 0,
    metadata_missing_count: int = 0,
) -> RealStorageWriteDryRunReport:
    report = _base_report(
        payload,
        names,
        working_dir,
        skipped=True,
        skip_reason=message,
        recommended_next_step="DO_NOT_WRITE_REAL_STORAGE",
    )
    report.vector_content_contamination_count = vector_content_contamination_count
    report.metadata_missing_count = metadata_missing_count
    report.issues.append({"severity": "ERROR", "code": code, "message": message})
    return report


def _error_report(
    payload: DslAwareIngestionPayload,
    names: dict[str, str],
    working_dir: Path,
    *,
    text_storage_type: str,
    vector_storage_type: str,
    message: str,
    cleanup_passed: bool,
    risks: list[str],
) -> RealStorageWriteDryRunReport:
    report = _base_report(
        payload,
        names,
        working_dir,
        skipped=True,
        skip_reason=message,
        recommended_next_step="FIX_TEST_STORAGE_INITIALIZATION",
    )
    report.text_chunks_storage_type = text_storage_type
    report.chunks_vdb_storage_type = vector_storage_type
    report.cleanup_passed = cleanup_passed
    report.risks.extend(risks)
    report.issues.append(
        {"severity": "ERROR", "code": "REAL_STORAGE_WRITE_FAILED", "message": message}
    )
    return report


def _base_report(
    payload: DslAwareIngestionPayload,
    names: dict[str, str],
    working_dir: Path,
    *,
    skipped: bool,
    skip_reason: str | None,
    recommended_next_step: str,
) -> RealStorageWriteDryRunReport:
    return RealStorageWriteDryRunReport(
        enabled=not skipped,
        skipped=skipped,
        skip_reason=skip_reason,
        document_id=payload.document_id,
        workspace=names["workspace"],
        working_dir=str(working_dir),
        text_chunks_namespace=names["text_chunks_namespace"],
        chunks_vdb_namespace=names["chunks_vdb_namespace"],
        text_chunks_storage_type="",
        chunks_vdb_storage_type="",
        selected_chunk_count=0,
        text_chunks_written_count=0,
        chunks_vdb_written_count=0,
        text_chunks_deleted_count=0,
        chunks_vdb_deleted_count=0,
        embedding_called=False,
        embedding_call_count=0,
        embedded_text_count=0,
        embedding_input_contamination_count=0,
        embedding_input_previews=[],
        vector_content_contamination_count=0,
        metadata_missing_count=0,
        text_chunks_metadata_retained_count=0,
        chunks_vdb_metadata_retained_count=0,
        idempotency_passed=False,
        rollback_passed=False,
        cleanup_passed=False,
        graph_written=False,
        extract_entities_called=False,
        merge_called=False,
        full_docs_written=False,
        doc_status_written=False,
        real_text_chunks_written=False,
        real_chunks_vdb_written=False,
        recommended_next_step=recommended_next_step,
    )


def _cleanup(
    working_dir: Path,
    config: RealStorageWriteDryRunConfig,
    risks: list[str],
) -> bool:
    if os.getenv(KEEP_TEST_DATA_ENV) == "1" or not config.cleanup_after_run:
        risks.append(f"Test data kept at {working_dir}.")
        return False
    try:
        shutil.rmtree(working_dir, ignore_errors=False)
    except FileNotFoundError:
        return True
    except Exception as exc:
        risks.append(f"Cleanup failed: {exc.__class__.__name__}: {exc}")
        return False
    return not working_dir.exists()


def _preview(content: str, limit: int = 160) -> str:
    compact = " ".join(content.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


__all__ = [
    "RealStorageWriteDryRunConfig",
    "RealStorageWriteDryRunReport",
    "RealStorageWriteItemResult",
    "arun_real_storage_write_dry_run",
    "run_real_storage_write_dry_run",
    "serialize_real_storage_write_dry_run_report",
]
