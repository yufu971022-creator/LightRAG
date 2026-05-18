from __future__ import annotations

import asyncio
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from .payload_types import DslAwareIngestionPayload
from .shadow_storage import ShadowKVStorage, ShadowVectorStorage
from .storage_mapping import (
    ChunksVdbShadowWriteItem,
    LightRagChunkCandidate,
    TextChunksShadowWriteItem,
    build_chunks_vdb_write_item,
    build_lightrag_chunk_candidates,
    build_text_chunks_write_item,
    md5_text_hash,
    vector_content_contaminated,
)


ENABLE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_STORAGE_SHADOW_WRITE"
RESET_ENV = "LIGHTRAG_DSL_STORAGE_SHADOW_RESET"
HARD_MAX_CHUNKS_ENV = "LIGHTRAG_DSL_STORAGE_SHADOW_HARD_MAX_CHUNKS"


@dataclass(frozen=True)
class StorageWriteDryRunConfig:
    enabled: bool = False
    dry_run: bool = True
    shadow_only: bool = True
    write_real_storage: bool = False
    feature_flag_name: str = "enable_dsl_aware_storage_shadow_write"
    require_quality_gate_not_fail: bool = True
    allow_warn_quality_gate: bool = True
    reset_before_write: bool = False
    hard_max_chunks: int | None = None

    @classmethod
    def from_env(cls) -> "StorageWriteDryRunConfig":
        return cls(
            enabled=os.getenv(ENABLE_ENV) == "1",
            reset_before_write=os.getenv(RESET_ENV) == "1",
            hard_max_chunks=_optional_env_int(HARD_MAX_CHUNKS_ENV),
        )


@dataclass(frozen=True)
class ShadowStorageWriteIssue:
    severity: str
    code: str
    message: str
    chunk_id: str | None = None


@dataclass
class ShadowStorageWriteReport:
    document_id: str
    dry_run: bool
    shadow_only: bool
    real_storage_written: bool
    embedding_called: bool
    graph_written: bool
    text_chunks_shadow_count: int
    chunks_vdb_shadow_count: int
    duplicate_chunk_id_count: int
    contamination_count: int
    missing_metadata_count: int
    idempotency_passed: bool
    rollback_supported: bool
    reset_supported: bool
    summary: dict[str, Any]
    issues: list[ShadowStorageWriteIssue] = field(default_factory=list)
    recommended_next_step: str = ""
    text_chunks_write_items: list[TextChunksShadowWriteItem] = field(default_factory=list)
    chunks_vdb_write_items: list[ChunksVdbShadowWriteItem] = field(default_factory=list)


def build_shadow_storage_write_plan(
    payload: DslAwareIngestionPayload,
    *,
    validate_quality_gate: bool = True,
    config: StorageWriteDryRunConfig | None = None,
) -> ShadowStorageWriteReport:
    config = config or StorageWriteDryRunConfig(enabled=True)
    _reject_real_write(config)
    issues: list[ShadowStorageWriteIssue] = []

    quality_status = _quality_gate_status(payload)
    if validate_quality_gate and quality_status == "FAIL":
        issues.append(
            ShadowStorageWriteIssue(
                severity="ERROR",
                code="QUALITY_GATE_FAIL",
                message="Payload qualityGate.status is FAIL.",
            )
        )
        return _empty_report(
            payload.document_id,
            issues=issues,
            recommended_next_step="DO_NOT_SHADOW_WRITE",
        )

    candidates = build_lightrag_chunk_candidates(payload)
    if config.hard_max_chunks is not None and len(candidates) > config.hard_max_chunks:
        candidates = candidates[: config.hard_max_chunks]
        issues.append(
            ShadowStorageWriteIssue(
                severity="WARN",
                code="SHADOW_CHUNK_CAP_APPLIED",
                message=f"Shadow write capped to {config.hard_max_chunks} chunks.",
            )
        )

    candidate_issues = _validate_candidates(candidates)
    issues.extend(candidate_issues)
    duplicate_count = _duplicate_count(candidate.chunk_id for candidate in candidates)
    if duplicate_count:
        issues.append(
            ShadowStorageWriteIssue(
                severity="WARN",
                code="DUPLICATE_CHUNK_ID",
                message=f"{duplicate_count} duplicate chunk ids found in payload.",
            )
        )

    text_items = [
        build_text_chunks_write_item(candidate) for candidate in candidates
    ]
    vdb_items = [
        build_chunks_vdb_write_item(candidate) for candidate in candidates
    ]
    blocking_issue = any(issue.severity == "ERROR" for issue in issues)
    return _report(
        payload.document_id,
        text_items=text_items if not blocking_issue else [],
        vdb_items=vdb_items if not blocking_issue else [],
        issues=issues,
        duplicate_chunk_id_count=duplicate_count,
        recommended_next_step=(
            "DO_NOT_SHADOW_WRITE" if blocking_issue else "CONSIDER_TEST_NAMESPACE_VECTOR_WRITE"
        ),
    )


def run_shadow_storage_write(
    payload: DslAwareIngestionPayload,
    *,
    text_chunks_shadow: ShadowKVStorage | None = None,
    chunks_vdb_shadow: ShadowVectorStorage | None = None,
    reset_before_write: bool = False,
    config: StorageWriteDryRunConfig | None = None,
) -> ShadowStorageWriteReport:
    return asyncio.run(
        arun_shadow_storage_write(
            payload,
            text_chunks_shadow=text_chunks_shadow,
            chunks_vdb_shadow=chunks_vdb_shadow,
            reset_before_write=reset_before_write,
            config=config,
        )
    )


async def arun_shadow_storage_write(
    payload: DslAwareIngestionPayload,
    *,
    text_chunks_shadow: ShadowKVStorage | None = None,
    chunks_vdb_shadow: ShadowVectorStorage | None = None,
    reset_before_write: bool = False,
    config: StorageWriteDryRunConfig | None = None,
) -> ShadowStorageWriteReport:
    config = config or StorageWriteDryRunConfig(enabled=True)
    _reject_real_write(config)
    text_chunks_shadow = text_chunks_shadow or ShadowKVStorage()
    chunks_vdb_shadow = chunks_vdb_shadow or ShadowVectorStorage()

    if reset_before_write or config.reset_before_write:
        text_chunks_shadow.reset()
        chunks_vdb_shadow.reset()

    report = build_shadow_storage_write_plan(payload, config=config)
    if report.recommended_next_step == "DO_NOT_SHADOW_WRITE":
        return report

    existing_text_keys = set(text_chunks_shadow.data)
    existing_vdb_keys = set(chunks_vdb_shadow.data)
    text_data = {item.key: item.value for item in report.text_chunks_write_items}
    vdb_data = {item.key: item.value for item in report.chunks_vdb_write_items}
    await text_chunks_shadow.upsert(text_data)
    await chunks_vdb_shadow.upsert(vdb_data)

    overwritten_text = len(existing_text_keys & set(text_data))
    overwritten_vdb = len(existing_vdb_keys & set(vdb_data))
    unique_count = len(set(text_data))
    idempotency_passed = (
        text_chunks_shadow.count() >= unique_count
        and chunks_vdb_shadow.count() >= unique_count
        and text_chunks_shadow.count() == chunks_vdb_shadow.count()
    )
    report.text_chunks_shadow_count = text_chunks_shadow.count()
    report.chunks_vdb_shadow_count = chunks_vdb_shadow.count()
    report.duplicate_chunk_id_count += max(overwritten_text, overwritten_vdb)
    report.idempotency_passed = idempotency_passed
    report.embedding_called = chunks_vdb_shadow.embedding_called
    report.reset_supported = True
    report.rollback_supported = True
    report.summary.update(
        {
            "textChunksShadowCount": report.text_chunks_shadow_count,
            "chunksVdbShadowCount": report.chunks_vdb_shadow_count,
            "overwrittenTextChunks": overwritten_text,
            "overwrittenChunksVdb": overwritten_vdb,
            "idempotencyPassed": report.idempotency_passed,
            "embeddingCalled": report.embedding_called,
        }
    )
    if report.embedding_called:
        report.issues.append(
            ShadowStorageWriteIssue(
                severity="ERROR",
                code="EMBEDDING_CALL_ATTEMPTED",
                message="Shadow vector storage reported embedding call.",
            )
        )
        report.recommended_next_step = "DO_NOT_SHADOW_WRITE"
    return report


def serialize_shadow_storage_write_report(
    report: ShadowStorageWriteReport,
) -> dict[str, Any]:
    return {
        "documentId": report.document_id,
        "dryRun": report.dry_run,
        "shadowOnly": report.shadow_only,
        "realStorageWritten": report.real_storage_written,
        "embeddingCalled": report.embedding_called,
        "graphWritten": report.graph_written,
        "textChunksShadowCount": report.text_chunks_shadow_count,
        "chunksVdbShadowCount": report.chunks_vdb_shadow_count,
        "duplicateChunkIdCount": report.duplicate_chunk_id_count,
        "contaminationCount": report.contamination_count,
        "missingMetadataCount": report.missing_metadata_count,
        "idempotencyPassed": report.idempotency_passed,
        "rollbackSupported": report.rollback_supported,
        "resetSupported": report.reset_supported,
        "summary": report.summary,
        "recommendedNextStep": report.recommended_next_step,
        "issues": [asdict(issue) for issue in report.issues],
        "textChunksWriteItems": [asdict(item) for item in report.text_chunks_write_items],
        "chunksVdbWriteItems": [asdict(item) for item in report.chunks_vdb_write_items],
    }


def _validate_candidates(
    candidates: list[LightRagChunkCandidate],
) -> list[ShadowStorageWriteIssue]:
    issues: list[ShadowStorageWriteIssue] = []
    for candidate in candidates:
        if not candidate.chunk_id:
            issues.append(_issue("ERROR", "MISSING_CHUNK_ID", "Missing chunk id."))
        if not candidate.content:
            issues.append(
                _issue("ERROR", "MISSING_CONTENT", "Missing content.", candidate.chunk_id)
            )
        if vector_content_contaminated(candidate.content):
            issues.append(
                _issue(
                    "ERROR",
                    "VECTOR_CONTENT_CONTAMINATED",
                    "Vector content contains synthetic DSL prompt markers.",
                    candidate.chunk_id,
                )
            )
        missing_metadata = _missing_metadata(candidate)
        if missing_metadata:
            issues.append(
                _issue(
                    "ERROR",
                    "MISSING_METADATA",
                    f"Missing metadata fields: {', '.join(missing_metadata)}.",
                    candidate.chunk_id,
                )
            )
        if candidate.text_hash and candidate.text_hash != md5_text_hash(candidate.content):
            issues.append(
                _issue(
                    "WARN",
                    "TEXT_HASH_MISMATCH",
                    "textHash does not match vector content md5.",
                    candidate.chunk_id,
                )
            )
    if not issues:
        issues.append(
            ShadowStorageWriteIssue(
                severity="INFO",
                code="SHADOW_WRITE_OK",
                message="Shadow write plan is valid.",
            )
        )
    return issues


def _missing_metadata(candidate: LightRagChunkCandidate) -> list[str]:
    required = {
        "full_doc_id": candidate.full_doc_id,
        "source_text_unit_id": candidate.source_text_unit_id,
        "section_type": candidate.section_type,
        "text_hash": candidate.text_hash,
        "source_span": candidate.source_span,
    }
    return [key for key, value in required.items() if value in (None, "", {})]


def _report(
    document_id: str,
    *,
    text_items: list[TextChunksShadowWriteItem],
    vdb_items: list[ChunksVdbShadowWriteItem],
    issues: list[ShadowStorageWriteIssue],
    duplicate_chunk_id_count: int,
    recommended_next_step: str,
) -> ShadowStorageWriteReport:
    contamination_count = sum(
        1 for issue in issues if issue.code == "VECTOR_CONTENT_CONTAMINATED"
    )
    missing_metadata_count = sum(
        1 for issue in issues if issue.code == "MISSING_METADATA"
    )
    report = ShadowStorageWriteReport(
        document_id=document_id,
        dry_run=True,
        shadow_only=True,
        real_storage_written=False,
        embedding_called=False,
        graph_written=False,
        text_chunks_shadow_count=len(text_items),
        chunks_vdb_shadow_count=len(vdb_items),
        duplicate_chunk_id_count=duplicate_chunk_id_count,
        contamination_count=contamination_count,
        missing_metadata_count=missing_metadata_count,
        idempotency_passed=duplicate_chunk_id_count == 0,
        rollback_supported=True,
        reset_supported=True,
        summary={},
        issues=issues,
        recommended_next_step=recommended_next_step,
        text_chunks_write_items=text_items,
        chunks_vdb_write_items=vdb_items,
    )
    report.summary = {
        "documentId": document_id,
        "textChunksShadowCount": report.text_chunks_shadow_count,
        "chunksVdbShadowCount": report.chunks_vdb_shadow_count,
        "duplicateChunkIdCount": report.duplicate_chunk_id_count,
        "contaminationCount": report.contamination_count,
        "missingMetadataCount": report.missing_metadata_count,
        "idempotencyPassed": report.idempotency_passed,
        "realStorageWritten": report.real_storage_written,
        "embeddingCalled": report.embedding_called,
        "graphWritten": report.graph_written,
        "rollbackSupported": report.rollback_supported,
        "resetSupported": report.reset_supported,
    }
    return report


def _empty_report(
    document_id: str,
    *,
    issues: list[ShadowStorageWriteIssue],
    recommended_next_step: str,
) -> ShadowStorageWriteReport:
    return _report(
        document_id,
        text_items=[],
        vdb_items=[],
        issues=issues,
        duplicate_chunk_id_count=0,
        recommended_next_step=recommended_next_step,
    )


def _reject_real_write(config: StorageWriteDryRunConfig) -> None:
    if config.write_real_storage:
        raise NotImplementedError(
            "Real LightRAG storage writes are not allowed in Block 11 shadow dry-run."
        )


def _quality_gate_status(payload: DslAwareIngestionPayload) -> str:
    quality_gate = payload.summary.get("qualityGate")
    if isinstance(quality_gate, dict):
        status = quality_gate.get("status")
        if isinstance(status, str):
            return status
    return ""


def _duplicate_count(values) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def _issue(
    severity: str,
    code: str,
    message: str,
    chunk_id: str | None = None,
) -> ShadowStorageWriteIssue:
    return ShadowStorageWriteIssue(
        severity=severity,
        code=code,
        message=message,
        chunk_id=chunk_id,
    )


def _optional_env_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "ShadowStorageWriteIssue",
    "ShadowStorageWriteReport",
    "StorageWriteDryRunConfig",
    "arun_shadow_storage_write",
    "build_shadow_storage_write_plan",
    "run_shadow_storage_write",
    "serialize_shadow_storage_write_report",
]
