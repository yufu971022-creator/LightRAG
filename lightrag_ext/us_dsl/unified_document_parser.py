from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from lightrag.operate import chunking_by_token_size
from lightrag.utils import compute_mdhash_id

from .raw_evidence_mapping import build_chunk_text_unit_links, calculate_mapping_coverage
from .source_text_unit_builder import build_source_text_units
from .unified_document_types import (
    RawEvidenceChunk,
    SourceTextUnitRef,
    UnifiedDocumentEnvelope,
    UnifiedParseConfig,
    UnifiedParseResult,
)


DSL_CONTEXT_FORBIDDEN_TERMS = (
    "DSL_CONTEXT",
    "allowedEntityTypes",
    "allowedRelationTypes",
    "Ontology Prompt",
    "Version Prompt",
    "Domain Prompt",
    "internal review status template",
)


class ParserSpy:
    def __init__(self) -> None:
        self.file_read_count = 0
        self.parser_call_count = 0


class _OfflineTokenizer:
    def encode(self, content: str) -> list[str]:
        return list(content)

    def decode(self, tokens: list[str]) -> str:
        return "".join(tokens)


def build_unified_parse_result(
    *,
    source_path: str | None = None,
    content: str | None = None,
    document_metadata: dict[str, Any] | None = None,
    config: UnifiedParseConfig | None = None,
    parser: Callable[[str], str] | None = None,
    spy: ParserSpy | None = None,
) -> UnifiedParseResult:
    config = config or UnifiedParseConfig()
    metadata = dict(document_metadata or {})
    spy = spy or ParserSpy()
    parse_started_at = _now()
    extracted_text = _read_or_use_content(source_path=source_path, content=content, spy=spy)
    spy.parser_call_count += 1
    normalized_text = _normalize_text(parser(extracted_text) if parser else extracted_text)
    parse_finished_at = _now()
    content_hash = _sha256(normalized_text)
    document_id = _document_id(source_path=source_path, metadata=metadata)
    document_version_id = _document_version_id(document_id, content_hash)
    envelope = UnifiedDocumentEnvelope(
        document_id=document_id,
        document_version_id=document_version_id,
        source_uri=metadata.get("source_uri"),
        source_path=str(source_path) if source_path else None,
        file_name=metadata.get("file_name") or (Path(source_path).name if source_path else None),
        file_type=metadata.get("file_type") or (Path(source_path).suffix.lstrip(".") if source_path else "text"),
        module_code=metadata.get("module_code") or config.module_code,
        content_hash=content_hash,
        extracted_text=extracted_text,
        normalized_text=normalized_text,
        parser_name=config.parser_name,
        parser_version=config.parser_version,
        parse_started_at=parse_started_at,
        parse_finished_at=parse_finished_at,
        metadata=metadata,
    )
    issues: list[str] = []
    raw_chunks = _build_raw_chunks(envelope, config, issues)
    source_units = _build_source_text_unit_refs(envelope)
    links = build_chunk_text_unit_links(raw_chunks, source_units)
    coverage = calculate_mapping_coverage(raw_chunks, source_units, links)
    if _dsl_context_contamination_count(raw_chunks) > 0:
        issues.append("dsl_context_contamination_detected")
    return UnifiedParseResult(
        document=envelope,
        raw_chunks=raw_chunks,
        source_text_units=source_units,
        chunk_text_unit_links=links,
        parser_call_count=spy.parser_call_count,
        file_read_count=spy.file_read_count,
        normalized_text_hash=_sha256(normalized_text),
        raw_chunk_coverage=coverage.raw_chunk_coverage,
        text_unit_coverage=coverage.text_unit_coverage,
        orphan_chunk_count=coverage.orphan_chunk_count,
        orphan_text_unit_count=coverage.orphan_text_unit_count,
        issues=issues,
        chunker={
            "chunker_name": config.chunker_name,
            "chunker_version": config.chunker_version,
            "chunk_size": config.chunk_token_size,
            "overlap": config.chunk_overlap_token_size,
        },
    )


def _read_or_use_content(*, source_path: str | None, content: str | None, spy: ParserSpy) -> str:
    if content is not None:
        return content
    if not source_path:
        raise ValueError("Either source_path or content must be provided")
    spy.file_read_count += 1
    return Path(source_path).read_text(encoding="utf-8")


def _normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(lines).strip()


def _build_raw_chunks(
    envelope: UnifiedDocumentEnvelope,
    config: UnifiedParseConfig,
    issues: list[str],
) -> list[RawEvidenceChunk]:
    if not envelope.normalized_text:
        issues.append("parse_failed_empty_text")
        return []
    tokenizer = _OfflineTokenizer()
    chunk_dicts = chunking_by_token_size(
        tokenizer,
        envelope.normalized_text,
        chunk_overlap_token_size=config.chunk_overlap_token_size,
        chunk_token_size=config.chunk_token_size,
    )
    chunks: list[RawEvidenceChunk] = []
    cursor = 0
    for item in chunk_dicts:
        content = item["content"]
        start = envelope.normalized_text.find(content, cursor)
        if start < 0:
            start = envelope.normalized_text.find(content)
        if start < 0:
            issues.append(f"chunk_offset_unresolved:{item.get('chunk_order_index')}")
            continue
        end = start + len(content)
        cursor = start if config.chunk_overlap_token_size else end
        content_hash = _sha256(content)
        chunk_order = int(item.get("chunk_order_index", len(chunks)))
        chunks.append(
            RawEvidenceChunk(
                chunk_id=compute_mdhash_id(
                    f"{envelope.document_version_id}:{chunk_order}:{content_hash}", prefix="chunk-"
                ),
                document_id=envelope.document_id,
                document_version_id=envelope.document_version_id,
                chunk_order=chunk_order,
                content=content,
                start_offset=start,
                end_offset=end,
                token_count=int(item.get("tokens", len(tokenizer.encode(content)))),
                content_hash=content_hash,
                source_span={"start": start, "end": end},
                metadata={
                    "chunker_name": config.chunker_name,
                    "chunker_version": config.chunker_version,
                },
            )
        )
    return chunks


def _build_source_text_unit_refs(envelope: UnifiedDocumentEnvelope) -> list[SourceTextUnitRef]:
    units = build_source_text_units(
        envelope.normalized_text,
        document_id=envelope.document_id,
        file_path=envelope.file_name or envelope.source_path,
    )
    refs: list[SourceTextUnitRef] = []
    for unit in units:
        refs.append(
            SourceTextUnitRef(
                text_unit_id=unit.text_unit_id,
                document_id=unit.document_id,
                document_version_id=envelope.document_version_id,
                source_us_id=unit.us_id,
                section_type=unit.section_type,
                content=unit.chunk_text,
                start_offset=int(unit.source_span["start"]),
                end_offset=int(unit.source_span["end"]),
                text_hash=unit.text_hash,
                feature_key=unit.feature_key,
                primary_domain=unit.domain_code,
                related_domains=[] if unit.domain_code is None else [unit.domain_code],
                metadata={
                    "chunk_index": unit.chunk_index,
                    "file_path": unit.file_path,
                    "source_text_unit_semantics": "reused_from_lightrag_ext.us_dsl.dsl_types.SourceTextUnit",
                },
            )
        )
    return refs


def _document_id(*, source_path: str | None, metadata: dict[str, Any]) -> str:
    if metadata.get("document_id"):
        return str(metadata["document_id"])
    stable_source = metadata.get("source_uri") or metadata.get("logical_source")
    if not stable_source and source_path:
        path = Path(source_path)
        stable_source = f"{path.name}:{path.suffix}"
    stable_source = stable_source or "inline_document"
    return "doc-" + hashlib.md5(str(stable_source).encode("utf-8")).hexdigest()


def _document_version_id(document_id: str, content_hash: str) -> str:
    return "docver-" + hashlib.md5(f"{document_id}:{content_hash}".encode("utf-8")).hexdigest()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _dsl_context_contamination_count(chunks: list[RawEvidenceChunk]) -> int:
    return sum(
        1
        for chunk in chunks
        if any(term in chunk.content for term in DSL_CONTEXT_FORBIDDEN_TERMS)
    )


def dsl_context_contamination_count(chunks: list[RawEvidenceChunk]) -> int:
    return _dsl_context_contamination_count(chunks)
