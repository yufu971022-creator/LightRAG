from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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

EDIT_NONE = "NONE"
EDIT_MINOR = "MINOR"
EDIT_MAJOR = "MAJOR"
EDIT_REWRITE = "REWRITE"

ADOPT_ACCEPT_AS_IS = "ACCEPT_AS_IS"
ADOPT_ACCEPT_MINOR = "ACCEPT_WITH_MINOR_EDITS"
ADOPT_MAJOR_REVISION = "NEED_MAJOR_REVISION"
ADOPT_REJECT = "REJECT"


@dataclass(frozen=True)
class USGenerationCase:
    case_id: str
    module_name: str
    case_pack_name: str
    level: str
    user_request: str
    generation_task_type: str
    expected_us_sections: list[str]
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
class USGenerationResult:
    case_id: str
    mode: str
    generated_us_markdown: str
    generated_sections: list[str] = field(default_factory=list)
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
class USGenerationJudgement:
    case_id: str
    mode: str
    score: int
    result: str
    structure_completeness_score: int
    business_rule_coverage_score: int
    evidence_grounding_score: int
    source_span_score: int
    consistency_with_existing_knowledge_score: int
    version_handling_score: int
    dfx_coverage_score: int
    review_readiness_score: int
    unsupported_claim_count: int
    invalid_citation_count: int
    missing_expected_sections: list[str] = field(default_factory=list)
    missing_expected_points: list[str] = field(default_factory=list)
    covered_expected_points: list[str] = field(default_factory=list)
    false_positive_claims: list[str] = field(default_factory=list)
    candidate_as_confirmed_count: int = 0
    info_only_as_fact_count: int = 0
    estimated_human_edit_level: str = EDIT_MAJOR
    adoption_level: str = ADOPT_MAJOR_REVISION
    reasons: list[str] = field(default_factory=list)


@dataclass
class USGenerationComparisonResult:
    case_id: str
    text_only_judgement: USGenerationJudgement
    graph_aware_judgement: USGenerationJudgement
    score_delta: int
    evidence_grounding_delta: int
    source_span_delta: int
    unsupported_claim_delta: int
    structure_completeness_delta: int
    business_rule_coverage_delta: int
    review_readiness_delta: int
    adoption_level_delta: int
    improvement_label: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class USGenerationCaseResult:
    case: USGenerationCase
    graph_coverage_status: str
    missing_graph_objects: list[str]
    text_result: USGenerationResult
    graph_result: USGenerationResult
    text_judgement: USGenerationJudgement
    graph_judgement: USGenerationJudgement
    comparison: USGenerationComparisonResult


@dataclass(frozen=True)
class USGenerationAbEvalConfig:
    module_name: str
    case_pack_name: str
    max_cases: int = 8
    mode: str = MODE_OFFLINE
    allow_live_llm: bool = False
    live_env_var: str | None = None
    source: str = ""


@dataclass
class USGenerationAbEvalReport:
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
    avg_structure_completeness_delta: float
    avg_business_rule_coverage_delta: float
    avg_review_readiness_delta: float
    graph_path_used_count: int
    accept_as_is_count: int
    accept_with_minor_edits_count: int
    need_major_revision_count: int
    reject_count: int
    recommended_next_step: str
    risks: list[str] = field(default_factory=list)
    case_results: list[USGenerationCaseResult] = field(default_factory=list)
    llm_called: bool = False
    storage_written: bool = False
    neo4j_connected: bool = False


def serialize_dataclass(value: Any) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(value)


__all__ = [
    "ADOPT_ACCEPT_AS_IS",
    "ADOPT_ACCEPT_MINOR",
    "ADOPT_MAJOR_REVISION",
    "ADOPT_REJECT",
    "DEGRADED",
    "EDIT_MAJOR",
    "EDIT_MINOR",
    "EDIT_NONE",
    "EDIT_REWRITE",
    "FAIL",
    "GENERATION_DETERMINISTIC",
    "GENERATION_LIVE_LLM",
    "IMPROVED",
    "INCONCLUSIVE",
    "MODE_GRAPH_AWARE",
    "MODE_LIVE",
    "MODE_OFFLINE",
    "MODE_TEXT_ONLY",
    "PASS",
    "SAME",
    "USGenerationAbEvalConfig",
    "USGenerationAbEvalReport",
    "USGenerationCase",
    "USGenerationCaseResult",
    "USGenerationComparisonResult",
    "USGenerationJudgement",
    "USGenerationResult",
    "WARN",
    "serialize_dataclass",
]
