from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph_answer_types import AnswerGenerationResult


@dataclass(frozen=True)
class BusinessQaCase:
    case_id: str
    level: str
    question: str
    expected_behavior: str
    expected_answer_points: list[str]
    module_name: str = ""
    case_pack_name: str = ""
    expected_entities: list[str] = field(default_factory=list)
    expected_relations: list[str] = field(default_factory=list)
    expected_domains: list[str] = field(default_factory=list)
    expected_sections: list[str] = field(default_factory=list)
    expected_evidence_keywords: list[str] = field(default_factory=list)
    expected_source_us_ids: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    must_not_do: list[str] = field(default_factory=list)
    grading_notes: str = ""
    graph_coverage_expectation: str = "partial"
    expected_graph_coverage: str | None = None


@dataclass(frozen=True)
class BusinessQaAbEvalConfig:
    module_name: str
    case_pack_name: str
    max_cases: int = 10
    mode: str = "offline"
    allow_live_llm: bool = False
    graph_subset_limits: dict[str, int] = field(default_factory=dict)
    live_env_var: str | None = None
    source: str = ""


@dataclass(frozen=True)
class BusinessQaCaseCoverage:
    case_id: str
    level: str
    question: str
    coverage_status: str
    covered_entities: list[str] = field(default_factory=list)
    missing_entities: list[str] = field(default_factory=list)
    covered_relations: list[str] = field(default_factory=list)
    missing_relations: list[str] = field(default_factory=list)
    graph_coverage_reason: str = ""


@dataclass(frozen=True)
class BusinessQaGraphCoverageReport:
    case_count: int
    covered_case_count: int
    partial_case_count: int
    uncovered_case_count: int
    case_coverage: dict[str, str]
    missing_entities_by_case: dict[str, list[str]]
    missing_relations_by_case: dict[str, list[str]]
    graph_entity_coverage_ratio: float
    graph_relation_coverage_ratio: float
    recommended_subset_limits: dict[str, int]
    full_coverage_count: int = 0
    partial_coverage_count: int = 0
    no_coverage_count: int = 0
    module_name: str = ""
    case_pack_name: str = ""
    coverage_ratio: float = 0.0
    entity_coverage_ratio: float = 0.0
    relation_coverage_ratio: float = 0.0
    cases: list[BusinessQaCaseCoverage] = field(default_factory=list)
    selected_chunk_count: int = 0
    selected_entity_count: int = 0
    selected_relationship_count: int = 0
    selected_entities: list[str] = field(default_factory=list)
    selected_relations: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommended_next_step: str = ""


@dataclass
class BusinessQaAnswer:
    case_id: str
    mode: str
    answer_text: str
    cited_evidence_ids: list[str] = field(default_factory=list)
    cited_source_us_ids: list[str] = field(default_factory=list)
    cited_text_unit_ids: list[str] = field(default_factory=list)
    cited_graph_paths: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    candidate_as_confirmed_count: int = 0
    info_only_as_fact_count: int = 0
    graph_path_used: bool = False
    generation_mode: str = "deterministic"
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BusinessQaJudgement:
    case_id: str
    mode: str
    score: float
    result: str
    answer_completeness_score: int
    evidence_grounding_score: int
    source_span_score: int
    business_correctness_score: int
    unsupported_claim_count: int
    invalid_citation_count: int
    missing_expected_points: list[str] = field(default_factory=list)
    covered_expected_points: list[str] = field(default_factory=list)
    false_positive_claims: list[str] = field(default_factory=list)
    candidate_as_confirmed_count: int = 0
    info_only_as_fact_count: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass
class BusinessQaCaseResult:
    case: Any
    graph_coverage_status: str
    missing_graph_objects: list[str]
    text_answer: AnswerGenerationResult
    graph_answer: AnswerGenerationResult
    text_judgement: BusinessQaJudgement
    graph_judgement: BusinessQaJudgement
    improvement_label: str
    reasons: list[str] = field(default_factory=list)
    graph_path_used: bool = False


@dataclass
class BusinessQaComparisonResult:
    case_id: str
    text_only_judgement: BusinessQaJudgement
    graph_aware_judgement: BusinessQaJudgement
    score_delta: float
    evidence_grounding_delta: int
    source_span_delta: int
    unsupported_claim_delta: int
    improvement_label: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class BusinessQaAbEvalReport:
    source: str
    module_name: str
    case_pack_name: str
    case_count: int
    text_only_pass_count: int
    graph_aware_pass_count: int
    improved_count: int
    same_count: int
    degraded_count: int
    inconclusive_count: int
    avg_text_score: float
    avg_graph_score: float
    avg_score_delta: float
    avg_evidence_grounding_delta: float
    avg_source_span_delta: float
    avg_unsupported_claim_delta: float
    graph_path_used_count: int
    cases_with_invalid_citation: int
    cases_with_candidate_as_confirmed: int
    recommended_next_step: str
    risks: list[str] = field(default_factory=list)
    coverage_report: BusinessQaGraphCoverageReport | None = None
    case_results: list[BusinessQaCaseResult] = field(default_factory=list)
    llm_called: bool = False
    storage_written: bool = False
    neo4j_connected: bool = False


def business_case_coverage_expectation(case: Any) -> str:
    legacy = getattr(case, "expected_graph_coverage", None)
    if legacy:
        return str(legacy)
    return str(getattr(case, "graph_coverage_expectation", "partial"))


__all__ = [
    "BusinessQaAbEvalConfig",
    "BusinessQaAbEvalReport",
    "BusinessQaAnswer",
    "BusinessQaCase",
    "BusinessQaCaseCoverage",
    "BusinessQaCaseResult",
    "BusinessQaComparisonResult",
    "BusinessQaGraphCoverageReport",
    "BusinessQaJudgement",
    "business_case_coverage_expectation",
]
