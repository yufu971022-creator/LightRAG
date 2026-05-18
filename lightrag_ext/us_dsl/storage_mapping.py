from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .payload_types import DslAwareIngestionPayload, VectorPayloadItem


SYNTHETIC_VECTOR_MARKERS = (
    "<DSL_CONTEXT>",
    "</DSL_CONTEXT>",
    "<SOURCE_TEXT>",
    "</SOURCE_TEXT>",
)


@dataclass(frozen=True)
class LightRagChunkCandidate:
    chunk_id: str
    content: str
    full_doc_id: str
    file_path: str | None
    chunk_order_index: int
    tokens: int | None
    metadata: dict[str, Any]
    source_text_unit_id: str
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str
    text_hash: str
    source_span: dict[str, Any]

    def to_lightrag_chunk_value(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "full_doc_id": self.full_doc_id,
            "tokens": self.tokens,
            "chunk_order_index": self.chunk_order_index,
            "file_path": self.file_path or "",
            "llm_cache_list": [],
            "metadata": self.metadata,
            "source_text_unit_id": self.source_text_unit_id,
            "source_us_id": self.source_us_id,
            "feature_key": self.feature_key,
            "domain_code": self.domain_code,
            "section_type": self.section_type,
            "text_hash": self.text_hash,
            "source_span": self.source_span,
        }


@dataclass(frozen=True)
class TextChunksShadowWriteItem:
    key: str
    value: dict[str, Any]
    target: str = "text_chunks"
    would_write: bool = True
    real_write: bool = False
    overwrite_existing: bool = False
    idempotency_key: str = ""


@dataclass(frozen=True)
class ChunksVdbShadowWriteItem:
    key: str
    value: dict[str, Any]
    target: str = "chunks_vdb"
    would_write: bool = True
    real_write: bool = False
    would_call_embedding: bool = False
    overwrite_existing: bool = False
    idempotency_key: str = ""


def build_lightrag_chunk_candidates(
    payload: DslAwareIngestionPayload,
) -> list[LightRagChunkCandidate]:
    candidates: list[LightRagChunkCandidate] = []
    for index, item in enumerate(payload.vector_payload):
        candidates.append(_candidate_from_vector_item(item, payload.document_id, index))
    return candidates


def vector_content_contaminated(content: str) -> bool:
    return any(marker in content for marker in SYNTHETIC_VECTOR_MARKERS)


def md5_text_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]


def build_text_chunks_write_item(
    candidate: LightRagChunkCandidate,
    *,
    overwrite_existing: bool = False,
) -> TextChunksShadowWriteItem:
    return TextChunksShadowWriteItem(
        key=candidate.chunk_id,
        value=candidate.to_lightrag_chunk_value(),
        overwrite_existing=overwrite_existing,
        idempotency_key=_idempotency_key(candidate),
    )


def build_chunks_vdb_write_item(
    candidate: LightRagChunkCandidate,
    *,
    overwrite_existing: bool = False,
) -> ChunksVdbShadowWriteItem:
    return ChunksVdbShadowWriteItem(
        key=candidate.chunk_id,
        value=candidate.to_lightrag_chunk_value(),
        overwrite_existing=overwrite_existing,
        idempotency_key=_idempotency_key(candidate),
    )


def _candidate_from_vector_item(
    item: VectorPayloadItem,
    document_id: str,
    index: int,
) -> LightRagChunkCandidate:
    metadata = dict(item.metadata)
    source_span = metadata.get("sourceSpan")
    if not isinstance(source_span, dict):
        source_span = {}
    text_unit_id = _metadata_str(metadata, "textUnitId") or item.chunk_id
    return LightRagChunkCandidate(
        chunk_id=item.chunk_id,
        content=item.content,
        full_doc_id=_metadata_str(metadata, "documentId") or document_id,
        file_path=_metadata_str(metadata, "filePath"),
        chunk_order_index=index,
        tokens=None,
        metadata={
            **metadata,
            "sourceEvidence": {
                "documentId": _metadata_str(metadata, "documentId") or document_id,
                "sourceUsId": _metadata_str(metadata, "sourceUsId"),
                "textUnitId": text_unit_id,
                "sourceSpan": source_span,
                "textHash": _metadata_str(metadata, "textHash") or "",
            },
        },
        source_text_unit_id=text_unit_id,
        source_us_id=_metadata_str(metadata, "sourceUsId"),
        feature_key=_metadata_str(metadata, "featureKey"),
        domain_code=_metadata_str(metadata, "domainCode"),
        section_type=_metadata_str(metadata, "sectionType") or "",
        text_hash=_metadata_str(metadata, "textHash") or "",
        source_span=source_span,
    )


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _idempotency_key(candidate: LightRagChunkCandidate) -> str:
    raw = "|".join(
        [
            candidate.chunk_id,
            candidate.full_doc_id,
            candidate.text_hash,
            candidate.section_type,
        ]
    )
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "ChunksVdbShadowWriteItem",
    "LightRagChunkCandidate",
    "SYNTHETIC_VECTOR_MARKERS",
    "TextChunksShadowWriteItem",
    "build_chunks_vdb_write_item",
    "build_lightrag_chunk_candidates",
    "build_text_chunks_write_item",
    "md5_text_hash",
    "vector_content_contaminated",
]
