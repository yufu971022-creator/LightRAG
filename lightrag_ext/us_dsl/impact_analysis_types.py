from __future__ import annotations

from dataclasses import dataclass, field


MODE_TEXT_ONLY = "text_only"
MODE_GRAPH_AWARE = "graph_aware"
MODE_OFFLINE = "offline"
MODE_LIVE = "live"

GENERATION_DETERMINISTIC = "deterministic"
GENERATION_LIVE_LLM = "live_llm"

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

IMPROVED = "IMPROVED"
SAME = "SAME"
DEGRADED = "DEGRADED"
INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class ImpactAnalysisCase:
    case_id: str
    module_name: str
    case_pack_name: str
    level: str
    change_request: str
    impact_task_type: str
    expected_impact_dimensions: list[str]
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


@dataclass
class ImpactAnalysisResult:
    case_id: str
    mode: str
    analysis_markdown: str
    impacted_entities: list[str] = field(default_factory=list)
    impacted_relations: list[str] = field(default_factory=list)
    impacted_domains: list[str] = field(default_factory=list)
    impacted_sections: list[str] = field(default_factory=list)
    cited_evidence_ids: list[str] = field(default_factory=list)
    cited_source_us_ids: list[str] = field(default_factory=list)
    cited_text_unit_ids: list[str] = field(default_factory=list)
    cited_graph_paths: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    candidate_as_confirmed_count: int = 0
    info_only_as_fact_count: int = 0
    graph_path_used: bool = False
    generation_mode: str = GENERATION_DETERMINISTIC
    issues: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImpactAnalysisJudgement:
    case_id: str
    mode: str
    score: int
    result: str
    impact_completeness_score: int
    relation_path_score: int
    evidence_grounding_score: int
    source_span_score: int
    risk_control_score: int
    review_readiness_score: int
    unsupported_claim_count: int
    invalid_citation_count: int
    missing_expected_dimensions: list[str] = field(default_factory=list)
    missing_expected_entities: list[str] = field(default_factory=list)
    missing_expected_relations: list[str] = field(default_factory=list)
    covered_expected_entities: list[str] = field(default_factory=list)
    covered_expected_relations: list[str] = field(default_factory=list)
    false_positive_claims: list[str] = field(default_factory=list)
    candidate_as_confirmed_count: int = 0
    info_only_as_fact_count: int = 0
    reasons: list[str] = field(default_factory=list)


@dataclass
class ImpactAnalysisComparisonResult:
    case_id: str
    text_only_judgement: ImpactAnalysisJudgement
    graph_aware_judgement: ImpactAnalysisJudgement
    score_delta: int
    impact_completeness_delta: int
    relation_path_delta: int
    evidence_grounding_delta: int
    source_span_delta: int
    unsupported_claim_delta: int
    improvement_label: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class ImpactAnalysisCaseResult:
    case: ImpactAnalysisCase
    graph_coverage_status: str
    missing_graph_objects: list[str]
    text_result: ImpactAnalysisResult
    graph_result: ImpactAnalysisResult
    text_judgement: ImpactAnalysisJudgement
    graph_judgement: ImpactAnalysisJudgement
    comparison: ImpactAnalysisComparisonResult


@dataclass(frozen=True)
class ImpactAnalysisAbEvalConfig:
    module_name: str
    case_pack_name: str
    max_cases: int = 6
    mode: str = MODE_OFFLINE
    allow_live_llm: bool = False
    live_env_var: str | None = None
    source: str = ""


@dataclass
class ImpactAnalysisAbEvalReport:
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
    avg_impact_completeness_delta: float
    avg_relation_path_delta: float
    avg_evidence_grounding_delta: float
    avg_source_span_delta: float
    avg_unsupported_claim_delta: float
    graph_path_used_count: int
    cases_with_invalid_citation: int
    cases_with_candidate_as_confirmed: int
    recommended_next_step: str
    risks: list[str] = field(default_factory=list)
    case_results: list[ImpactAnalysisCaseResult] = field(default_factory=list)
    llm_called: bool = False
    storage_written: bool = False
    neo4j_connected: bool = False


__all__ = [
    "DEGRADED",
    "FAIL",
    "GENERATION_DETERMINISTIC",
    "GENERATION_LIVE_LLM",
    "IMPROVED",
    "INCONCLUSIVE",
    "ImpactAnalysisAbEvalConfig",
    "ImpactAnalysisAbEvalReport",
    "ImpactAnalysisCase",
    "ImpactAnalysisCaseResult",
    "ImpactAnalysisComparisonResult",
    "ImpactAnalysisJudgement",
    "ImpactAnalysisResult",
    "MODE_GRAPH_AWARE",
    "MODE_LIVE",
    "MODE_OFFLINE",
    "MODE_TEXT_ONLY",
    "PASS",
    "SAME",
    "WARN",
]
