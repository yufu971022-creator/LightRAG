from __future__ import annotations

from lightrag_ext.us_dsl.raw_evidence_mapping import (
    build_chunk_text_unit_links,
    calculate_mapping_coverage,
)
from lightrag_ext.us_dsl.unified_document_parser import build_unified_parse_result
from lightrag_ext.us_dsl.unified_document_types import RawEvidenceChunk, SourceTextUnitRef, UnifiedParseConfig


TEXT = """User Story: US-2401 Bank Status query conditions must be searchable.
Acceptance Criteria: Evidence: Bank Status supports Query Condition filtering.
Business Rule: Bank Status is canonical master data for query conditions.
Source: synthetic Block 24B-1 fixture.
"""


def _parse():
    return build_unified_parse_result(
        content=TEXT,
        document_metadata={"document_id": "doc-mapping-fixture", "file_name": "mapping.md"},
        config=UnifiedParseConfig(chunk_token_size=128),
    )


def test_chunk_text_unit_mapping_uses_offsets():
    result = _parse()

    assert result.chunk_text_unit_links
    assert all(link.evidence["mapping_basis"] == "document_version_id+offset_interval" for link in result.chunk_text_unit_links)
    assert all(link.overlap_start_offset < link.overlap_end_offset for link in result.chunk_text_unit_links)


def test_mapping_coverage_is_complete():
    chunk = _chunk("chunk-a", 0, 10, "0123456789")
    unit = _unit("unit-a", 0, 10, "0123456789")
    links = build_chunk_text_unit_links([chunk], [unit])
    coverage = calculate_mapping_coverage([chunk], [unit], links)

    assert coverage.raw_chunk_coverage == 1.0
    assert coverage.text_unit_coverage == 1.0


def test_no_orphan_chunks():
    result = _parse()

    assert result.orphan_chunk_count == 0


def test_no_orphan_text_units():
    result = _parse()

    assert result.orphan_text_unit_count == 0


def test_mapping_is_deterministic():
    first = _parse()
    second = _parse()

    assert [link.link_id for link in first.chunk_text_unit_links] == [link.link_id for link in second.chunk_text_unit_links]


def test_overlap_chunk_mapping_is_supported():
    chunks = [
        _chunk("chunk-a", 0, 10, "abcdefghij"),
        _chunk("chunk-b", 5, 15, "fghijklmno"),
    ]
    unit = _unit("unit-overlap", 3, 12, "defghijkl")

    links = build_chunk_text_unit_links(chunks, [unit])

    assert len(links) == 2
    assert {link.link_type for link in links} == {"OVERLAPS"}
    assert sum(link.overlap_char_count for link in links) == 14


def _chunk(chunk_id: str, start: int, end: int, content: str) -> RawEvidenceChunk:
    return RawEvidenceChunk(
        chunk_id=chunk_id,
        document_id="doc-map",
        document_version_id="docver-map",
        chunk_order=0,
        content=content,
        start_offset=start,
        end_offset=end,
        token_count=len(content),
        content_hash=f"hash-{chunk_id}",
        source_span={"start": start, "end": end},
    )


def _unit(unit_id: str, start: int, end: int, content: str) -> SourceTextUnitRef:
    return SourceTextUnitRef(
        text_unit_id=unit_id,
        document_id="doc-map",
        document_version_id="docver-map",
        source_us_id=None,
        section_type="body",
        content=content,
        start_offset=start,
        end_offset=end,
        text_hash=f"hash-{unit_id}",
        feature_key=None,
        primary_domain=None,
    )
