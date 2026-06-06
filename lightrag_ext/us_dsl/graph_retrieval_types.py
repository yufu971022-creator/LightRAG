from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MODE_TEXT_ONLY = "text_only"
MODE_GRAPH_AWARE = "graph_aware"

HIT_TEXT = "text"
HIT_NODE = "node"
HIT_EDGE = "edge"
HIT_PATH = "path"

IMPROVED = "IMPROVED"
SAME = "SAME"
DEGRADED = "DEGRADED"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class GraphRetrievalQuery:
    query_id: str
    query_text: str
    expected_focus: list[str] = field(default_factory=list)
    expected_domains: list[str] = field(default_factory=list)
    expected_sections: list[str] = field(default_factory=list)
    expected_entities: list[str] = field(default_factory=list)
    expected_relations: list[str] = field(default_factory=list)
    expected_evidence_keywords: list[str] = field(default_factory=list)
    level: str = "L1"


@dataclass(frozen=True)
class RetrievalHit:
    hit_type: str
    score: float
    source_id: str | None = None
    source_us_id: str | None = None
    text_unit_id: str | None = None
    domain_code: str | None = None
    feature_key: str | None = None
    section_type: str | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    relation_type: str | None = None
    path: list[dict[str, Any]] | None = None
    evidence_text: str | None = None
    source_span: dict[str, Any] | None = None
    text_hash: str | None = None
    reason: str = ""


@dataclass
class RetrievalResult:
    query_id: str
    query_text: str
    mode: str
    hits: list[RetrievalHit]
    expected_entities: list[str] = field(default_factory=list)
    expected_relations: list[str] = field(default_factory=list)
    expected_evidence_keywords: list[str] = field(default_factory=list)
    evidence_coverage: float = 0.0
    expected_entity_recall: float = 0.0
    expected_relation_recall: float = 0.0
    source_span_coverage: float = 0.0
    graph_path_count: int = 0
    unsupported_claim_risk: float = 0.0
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RetrievalComparisonResult:
    query_id: str
    text_only_result: RetrievalResult
    graph_aware_result: RetrievalResult
    entity_recall_delta: float
    relation_recall_delta: float
    evidence_coverage_delta: float
    source_span_coverage_delta: float
    graph_path_delta: int
    improvement_label: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class GraphRetrievalEvaluationReport:
    source: str
    query_count: int
    improved_count: int
    same_count: int
    degraded_count: int
    inconclusive_count: int
    avg_entity_recall_delta: float
    avg_relation_recall_delta: float
    avg_evidence_coverage_delta: float
    avg_source_span_coverage_delta: float
    avg_graph_path_delta: float
    recommended_next_step: str
    risks: list[str] = field(default_factory=list)
    comparison_results: list[RetrievalComparisonResult] = field(default_factory=list)


__all__ = [
    "DEGRADED",
    "HIT_EDGE",
    "HIT_NODE",
    "HIT_PATH",
    "HIT_TEXT",
    "IMPROVED",
    "INCONCLUSIVE",
    "MODE_GRAPH_AWARE",
    "MODE_TEXT_ONLY",
    "GraphRetrievalEvaluationReport",
    "GraphRetrievalQuery",
    "RetrievalComparisonResult",
    "RetrievalHit",
    "RetrievalResult",
    "SAME",
]
