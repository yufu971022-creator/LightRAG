from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .unified_document_types import ChunkTextUnitLink, RawEvidenceChunk, SourceTextUnitRef


@dataclass(frozen=True)
class MappingCoverage:
    raw_chunk_coverage: float
    text_unit_coverage: float
    orphan_chunk_count: int
    orphan_text_unit_count: int


def build_chunk_text_unit_links(
    raw_chunks: list[RawEvidenceChunk],
    source_text_units: list[SourceTextUnitRef],
) -> list[ChunkTextUnitLink]:
    links: list[ChunkTextUnitLink] = []
    for chunk in raw_chunks:
        for unit in source_text_units:
            if chunk.document_version_id != unit.document_version_id:
                continue
            overlap_start = max(chunk.start_offset, unit.start_offset)
            overlap_end = min(chunk.end_offset, unit.end_offset)
            overlap = max(0, overlap_end - overlap_start)
            if overlap <= 0:
                continue
            chunk_len = max(1, chunk.end_offset - chunk.start_offset)
            unit_len = max(1, unit.end_offset - unit.start_offset)
            links.append(
                ChunkTextUnitLink(
                    link_id=_link_id(chunk.chunk_id, unit.text_unit_id, overlap_start, overlap_end),
                    document_id=chunk.document_id,
                    document_version_id=chunk.document_version_id,
                    chunk_id=chunk.chunk_id,
                    text_unit_id=unit.text_unit_id,
                    overlap_start_offset=overlap_start,
                    overlap_end_offset=overlap_end,
                    overlap_char_count=overlap,
                    chunk_coverage_ratio=round(overlap / chunk_len, 6),
                    text_unit_coverage_ratio=round(overlap / unit_len, 6),
                    link_type=_link_type(chunk, unit, overlap_start, overlap_end),
                    evidence={
                        "mapping_basis": "document_version_id+offset_interval",
                        "chunk_content_hash": chunk.content_hash,
                        "text_unit_hash": unit.text_hash,
                    },
                )
            )
    return sorted(links, key=lambda item: (item.chunk_id, item.text_unit_id, item.overlap_start_offset))


def calculate_mapping_coverage(
    raw_chunks: list[RawEvidenceChunk],
    source_text_units: list[SourceTextUnitRef],
    links: list[ChunkTextUnitLink],
) -> MappingCoverage:
    chunk_coverage = _average_coverage(
        {chunk.chunk_id: max(1, chunk.end_offset - chunk.start_offset) for chunk in raw_chunks},
        links,
        key_attr="chunk_id",
    )
    unit_coverage = _average_coverage(
        {unit.text_unit_id: max(1, unit.end_offset - unit.start_offset) for unit in source_text_units},
        links,
        key_attr="text_unit_id",
    )
    linked_chunks = {link.chunk_id for link in links}
    linked_units = {link.text_unit_id for link in links}
    return MappingCoverage(
        raw_chunk_coverage=chunk_coverage,
        text_unit_coverage=unit_coverage,
        orphan_chunk_count=sum(1 for chunk in raw_chunks if chunk.chunk_id not in linked_chunks),
        orphan_text_unit_count=sum(1 for unit in source_text_units if unit.text_unit_id not in linked_units),
    )


def _average_coverage(lengths: dict[str, int], links: list[ChunkTextUnitLink], *, key_attr: str) -> float:
    if not lengths:
        return 0.0
    covered: dict[str, list[tuple[int, int]]] = {key: [] for key in lengths}
    for link in links:
        key = getattr(link, key_attr)
        if key in covered:
            covered[key].append((link.overlap_start_offset, link.overlap_end_offset))
    ratios = []
    for key, intervals in covered.items():
        ratios.append(min(1.0, _covered_chars(intervals) / lengths[key]))
    return round(sum(ratios) / len(ratios), 6)


def _covered_chars(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(intervals)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum(end - start for start, end in merged)


def _link_type(chunk: RawEvidenceChunk, unit: SourceTextUnitRef, start: int, end: int) -> str:
    if start == chunk.start_offset and end == chunk.end_offset and start == unit.start_offset and end == unit.end_offset:
        return "FULL"
    if start == unit.start_offset and end == unit.end_offset:
        return "CONTAINS"
    if start == chunk.start_offset and end == chunk.end_offset:
        return "PARTIAL"
    return "OVERLAPS"


def _link_id(chunk_id: str, text_unit_id: str, start: int, end: int) -> str:
    raw = f"{chunk_id}:{text_unit_id}:{start}:{end}"
    return "link-" + hashlib.md5(raw.encode("utf-8")).hexdigest()
