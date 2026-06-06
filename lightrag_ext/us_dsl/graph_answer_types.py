from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


GENERATION_DETERMINISTIC = "deterministic"
GENERATION_LIVE_LLM = "live_llm"


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source_us_id: str | None
    text_unit_id: str | None
    source_span: dict[str, Any] | None
    text_hash: str | None
    evidence_text: str
    feature_key: str | None
    domain_code: str | None
    section_type: str | None
    linked_entity: str | None = None
    linked_relation: str | None = None
    from_graph: bool = False


@dataclass(frozen=True)
class GraphPathEvidence:
    path_id: str
    nodes: list[str]
    edges: list[dict[str, Any]]
    relation_sequence: list[str]
    source_us_ids: list[str]
    evidence_texts: list[str]
    source_spans: list[dict[str, Any]]
    confidence_score: float


@dataclass(frozen=True)
class GraphAnswerContext:
    query_id: str
    query_text: str
    mode: str
    text_hits: list[Any] = field(default_factory=list)
    node_hits: list[Any] = field(default_factory=list)
    edge_hits: list[Any] = field(default_factory=list)
    path_hits: list[Any] = field(default_factory=list)
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    graph_paths: list[GraphPathEvidence] = field(default_factory=list)
    expected_entities: list[str] = field(default_factory=list)
    expected_relations: list[str] = field(default_factory=list)
    expected_evidence_keywords: list[str] = field(default_factory=list)
    guardrails: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AnswerGenerationResult:
    query_id: str
    mode: str
    answer_text: str
    cited_evidence_ids: list[str] = field(default_factory=list)
    cited_source_us_ids: list[str] = field(default_factory=list)
    cited_text_unit_ids: list[str] = field(default_factory=list)
    cited_graph_paths: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    missing_expected_items: list[str] = field(default_factory=list)
    graph_path_used: bool = False
    generation_mode: str = GENERATION_DETERMINISTIC
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerGroundingEvaluation:
    evidence_citation_count: int
    invalid_citation_count: int
    unsupported_claim_count: int
    unsupported_claim_ratio: float
    graph_path_used: bool
    candidate_as_confirmed_count: int
    info_only_as_fact_count: int
    grounding_passed: bool
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AnswerComparisonMetrics:
    query_id: str
    text_only_score: float
    graph_aware_score: float
    answer_completeness_delta: float
    evidence_citation_delta: int
    unsupported_claim_delta: int
    graph_path_usage_delta: int
    expected_entity_coverage_delta: float
    expected_relation_coverage_delta: float
    hallucination_risk_delta: float
    improvement_label: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class GraphAnswerEvaluationReport:
    source: str
    query_count: int
    improved_count: int
    same_count: int
    degraded_count: int
    inconclusive_count: int
    avg_answer_completeness_delta: float
    avg_evidence_citation_delta: float
    avg_unsupported_claim_delta: float
    avg_graph_path_usage_delta: float
    avg_expected_entity_coverage_delta: float
    avg_expected_relation_coverage_delta: float
    recommended_next_step: str
    risks: list[str] = field(default_factory=list)
    comparison_results: list[AnswerComparisonMetrics] = field(default_factory=list)


__all__ = [
    "GENERATION_DETERMINISTIC",
    "GENERATION_LIVE_LLM",
    "AnswerComparisonMetrics",
    "AnswerGenerationResult",
    "AnswerGroundingEvaluation",
    "EvidenceItem",
    "GraphAnswerContext",
    "GraphAnswerEvaluationReport",
    "GraphPathEvidence",
]
