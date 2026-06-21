from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class UnifiedDocumentEnvelope:
    document_id: str
    document_version_id: str
    source_uri: str | None
    source_path: str | None
    file_name: str | None
    file_type: str | None
    module_code: str | None
    content_hash: str
    extracted_text: str
    normalized_text: str
    parser_name: str
    parser_version: str
    parse_started_at: str
    parse_finished_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawEvidenceChunk:
    chunk_id: str
    document_id: str
    document_version_id: str
    chunk_order: int
    content: str
    start_offset: int
    end_offset: int
    token_count: int
    content_hash: str
    source_span: dict[str, int]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceTextUnitRef:
    text_unit_id: str
    document_id: str
    document_version_id: str
    source_us_id: str | None
    section_type: str
    content: str
    start_offset: int
    end_offset: int
    text_hash: str
    feature_key: str | None
    primary_domain: str | None
    related_domains: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChunkTextUnitLink:
    link_id: str
    document_id: str
    document_version_id: str
    chunk_id: str
    text_unit_id: str
    overlap_start_offset: int
    overlap_end_offset: int
    overlap_char_count: int
    chunk_coverage_ratio: float
    text_unit_coverage_ratio: float
    link_type: Literal["FULL", "PARTIAL", "CONTAINS", "OVERLAPS"]
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UnifiedParseConfig:
    parser_name: str = "unified_raw_evidence_parser"
    parser_version: str = "24B-1"
    chunk_token_size: int = 4096
    chunk_overlap_token_size: int = 0
    chunker_name: str = "lightrag.operate.chunking_by_token_size"
    chunker_version: str = "current"
    module_code: str | None = None


@dataclass(frozen=True)
class UnifiedParseResult:
    document: UnifiedDocumentEnvelope
    raw_chunks: list[RawEvidenceChunk]
    source_text_units: list[SourceTextUnitRef]
    chunk_text_unit_links: list[ChunkTextUnitLink]
    parser_call_count: int
    file_read_count: int
    normalized_text_hash: str
    raw_chunk_coverage: float
    text_unit_coverage: float
    orphan_chunk_count: int
    orphan_text_unit_count: int
    issues: list[str] = field(default_factory=list)
    chunker: dict[str, Any] = field(default_factory=dict)


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
