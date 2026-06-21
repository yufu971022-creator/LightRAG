from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.source_text_unit_builder import build_source_text_units
from lightrag_ext.us_dsl.unified_document_parser import (
    ParserSpy,
    build_unified_parse_result,
    dsl_context_contamination_count,
)
from lightrag_ext.us_dsl.unified_document_types import UnifiedParseConfig


SYNTHETIC_DESIGN_TEXT = """User Story: US-2401 Bank Status query conditions must be searchable.
Acceptance Criteria: Evidence: Bank Status supports Query Condition filtering.
Business Rule: Bank Status is canonical master data for query conditions.
Entity: Bank Status.
Field: Query Condition.
Relationship: Bank Status has Query Condition.
Source: synthetic Block 24B-1 fixture.
"""


def _parse(content: str = SYNTHETIC_DESIGN_TEXT):
    return build_unified_parse_result(
        content=content,
        document_metadata={"document_id": "doc-parser-fixture", "file_name": "fixture.md"},
        config=UnifiedParseConfig(chunk_token_size=128),
    )


def test_document_file_is_read_once(tmp_path: Path):
    source = tmp_path / "fixture.md"
    source.write_text(SYNTHETIC_DESIGN_TEXT, encoding="utf-8")
    spy = ParserSpy()

    result = build_unified_parse_result(
        source_path=str(source),
        document_metadata={"document_id": "doc-file-read-once"},
        config=UnifiedParseConfig(chunk_token_size=128),
        spy=spy,
    )

    assert result.file_read_count == 1
    assert spy.file_read_count == 1
    assert result.document.normalized_text.startswith("User Story")


def test_parser_is_called_once():
    calls = {"count": 0}

    def parser(text: str) -> str:
        calls["count"] += 1
        return text

    result = build_unified_parse_result(
        content=SYNTHETIC_DESIGN_TEXT,
        document_metadata={"document_id": "doc-parser-called-once"},
        parser=parser,
        config=UnifiedParseConfig(chunk_token_size=128),
    )

    assert calls["count"] == 1
    assert result.parser_call_count == 1


def test_raw_chunks_and_text_units_share_normalized_text():
    result = _parse()

    for chunk in result.raw_chunks:
        assert result.document.normalized_text[chunk.start_offset : chunk.end_offset] == chunk.content
    for unit in result.source_text_units:
        assert result.document.normalized_text[unit.start_offset : unit.end_offset] == unit.content


def test_document_id_is_stable_for_same_source():
    first = build_unified_parse_result(
        content="Same body",
        document_metadata={"source_uri": "synthetic://same-source", "file_name": "same.md"},
    )
    second = build_unified_parse_result(
        content="Same body with changed wording",
        document_metadata={"source_uri": "synthetic://same-source", "file_name": "same.md"},
    )

    assert first.document.document_id == second.document.document_id


def test_document_version_id_changes_when_content_changes():
    first = build_unified_parse_result(
        content="Version A",
        document_metadata={"source_uri": "synthetic://versioned"},
    )
    second = build_unified_parse_result(
        content="Version B",
        document_metadata={"source_uri": "synthetic://versioned"},
    )

    assert first.document.document_id == second.document.document_id
    assert first.document.document_version_id != second.document.document_version_id


def test_chunk_ids_are_deterministic():
    first = _parse()
    second = _parse()

    assert [chunk.chunk_id for chunk in first.raw_chunks] == [chunk.chunk_id for chunk in second.raw_chunks]


def test_raw_chunk_content_contains_no_dsl_context():
    result = _parse()

    assert dsl_context_contamination_count(result.raw_chunks) == 0
    assert "allowedEntityTypes" not in "\n".join(chunk.content for chunk in result.raw_chunks)


def test_source_text_units_reuse_existing_id_semantics():
    result = _parse()
    expected = build_source_text_units(
        result.document.normalized_text,
        document_id=result.document.document_id,
        file_path=result.document.file_name,
    )

    assert [unit.text_unit_id for unit in result.source_text_units] == [unit.text_unit_id for unit in expected]
    assert all(unit.metadata["source_text_unit_semantics"].startswith("reused_from") for unit in result.source_text_units)
