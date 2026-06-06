from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KgPayloadIssue:
    severity: str
    code: str
    message: str
    candidate_id: str | None = None
    source_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KgChunk:
    content: str
    source_id: str
    file_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KgEntity:
    entity_name: str
    entity_type: str
    description: str
    source_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KgRelationship:
    src_id: str
    tgt_id: str
    description: str
    keywords: str
    source_id: str
    weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphWriteEligibility:
    eligible_for_test_graph: bool
    eligible_for_formal_graph: bool
    reason: str


@dataclass
class DslKgPayload:
    chunks: list[KgChunk]
    entities: list[KgEntity]
    relationships: list[KgRelationship]
    metadata: dict[str, Any] = field(default_factory=dict)
    issues: list[KgPayloadIssue] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    entity_vdb_payload: list[dict[str, Any]] = field(default_factory=list)
    relationship_vdb_payload: list[dict[str, Any]] = field(default_factory=list)
    evidence_mapping: dict[str, Any] = field(default_factory=dict)
    version_mapping: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "DslKgPayload",
    "GraphWriteEligibility",
    "KgChunk",
    "KgEntity",
    "KgPayloadIssue",
    "KgRelationship",
]
