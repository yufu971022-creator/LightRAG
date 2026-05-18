from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorPayloadItem:
    chunk_id: str
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ExtractionPayloadItem:
    chunk_id: str
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MetadataPayloadItem:
    text_unit_id: str
    document_id: str
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str
    source_span: dict[str, int]
    text_hash: str
    vector_chunk_id: str
    extraction_chunk_id: str
    knowledge_status: str
    mapping_status: str


@dataclass(frozen=True)
class DslAwareIngestionIssue:
    severity: str
    code: str
    message: str
    text_unit_id: str | None = None
    feature_key: str | None = None
    source_us_id: str | None = None


@dataclass
class DslAwareIngestionPayload:
    document_id: str
    dsl_version: str
    source_text_unit_count: int
    dsl_aware_chunk_count: int
    vector_payload: list[VectorPayloadItem]
    extraction_payload: list[ExtractionPayloadItem]
    metadata_payload: list[MetadataPayloadItem]
    issues: list[DslAwareIngestionIssue] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
