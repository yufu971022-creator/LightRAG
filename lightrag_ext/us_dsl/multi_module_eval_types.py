from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from statistics import median
from typing import Any, Literal

SplitType = Literal["CALIBRATION", "HOLDOUT"]
CaseStatus = Literal["VALID", "INVALID_GOLD", "INCONCLUSIVE", "BLOCKED"]
GateStatus = Literal[
    "PASS",
    "FAIL_EFFECTIVENESS",
    "FAIL_SAFETY",
    "FAIL_MODULE_REGRESSION",
    "FAIL_HOLDOUT_GENERALIZATION",
    "FAIL_PERFORMANCE",
    "BLOCKED_INPUT_SET",
    "BLOCKED_ENV",
    "INCONCLUSIVE_GOLD",
]


@dataclass(frozen=True)
class MultiModulePolicy:
    minimum_real_module_count: int = 3
    minimum_holdout_module_count: int = 1
    minimum_domain_coverage: int = 5
    minimum_case_count_per_module: int = 8
    max_raw_recall_regression: float = 0.02
    max_per_module_recall_regression: float = 0.05
    max_invalid_citation_count: int = 0
    max_unsupported_factual_path_count: int = 0
    max_version_hard_judgment_error_count: int = 0
    max_generic_ner_fact_hit_count: int = 0
    max_query_p95_latency_ratio: float = 2.5
    max_ingestion_time_ratio: float = 4.0


@dataclass(frozen=True)
class ModuleManifestEntry:
    module_code: str
    module_name: str
    split: SplitType
    source_files: list[str]
    cases_file: str
    domains: list[str] = field(default_factory=list)
    term_registry: str | None = None
    domain_config: str | None = None
    version_config: str | None = None


@dataclass(frozen=True)
class MultiModuleManifest:
    suite_id: str
    output_dir: str
    policy: MultiModulePolicy
    modules: list[ModuleManifestEntry]


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    module_code: str
    task_type: str
    query: str
    strict_scope: bool
    version_intent: str | None
    as_of_time: str | None
    gold_source_refs: list[str]
    gold_source_us_ids: list[str]
    gold_text_unit_ids: list[str]
    gold_evidence_keywords: list[str]
    gold_semantic_object_ids: list[str]
    gold_relation_types: list[str]
    gold_required_dimensions: list[str]
    gold_forbidden_claims: list[str]
    gold_forbidden_claims_declared_none: bool = False
    gold_version_behavior: str | None = None
    risk_level: str = "MEDIUM"
    review_status: str = "REVIEWED"
    notes: str = ""
    one_to_n: bool = False


@dataclass(frozen=True)
class GoldCaseValidation:
    case_id: str
    module_code: str
    status: CaseStatus
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GoldValidationReport:
    valid_case_count: int
    invalid_gold_case_count: int
    case_results: list[GoldCaseValidation]
    duplicate_case_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievalHit:
    hit_id: str
    module_code: str
    source_ref: str | None = None
    source_us_id: str | None = None
    text_unit_id: str | None = None
    source_span: dict[str, int] = field(default_factory=dict)
    evidence_keywords: list[str] = field(default_factory=list)
    semantic_object_id: str | None = None
    relation_type: str | None = None
    required_dimensions: list[str] = field(default_factory=list)
    graph_path_id: str | None = None
    has_citation: bool = True
    unsupported_factual_path: bool = False
    issue_as_fact: bool = False
    candidate_as_confirmed: bool = False
    info_only_as_fact: bool = False
    generic_graph_override: bool = False
    generic_ner_fact_hit: bool = False
    version_hard_judgment_error: bool = False
    missing_version_warning: bool = False
    trust_tier: str = "T1_DIRECT"


@dataclass(frozen=True)
class CaseRetrievalResult:
    case_id: str
    module_code: str
    group: Literal["baseline", "candidate"]
    hits: list[RetrievalHit]
    latency_ms_runs: list[float] = field(default_factory=list)
    warmup_latency_ms: float | None = None
    status: str = "OK"


@dataclass(frozen=True)
class EffectivenessMetrics:
    evidence_recall_at_k: float
    evidence_precision_at_k: float
    entity_recall_at_k: float
    relation_recall_at_k: float
    required_dimension_coverage: float
    graph_path_coverage: float
    source_span_match_rate: float
    cross_language_alias_recall: float
    text_only_fallback_success_rate: float


@dataclass(frozen=True)
class SafetyMetrics:
    invalid_citation_count: int = 0
    unsupported_factual_path_count: int = 0
    issue_as_fact_count: int = 0
    candidate_as_confirmed_count: int = 0
    info_only_as_fact_count: int = 0
    generic_graph_override_count: int = 0
    generic_ner_fact_hit_count: int = 0
    version_hard_judgment_error_count: int = 0
    missing_version_warning_count: int = 0


@dataclass(frozen=True)
class LatencyStats:
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float
    measured_run_count: int
    warmup_excluded: bool


@dataclass(frozen=True)
class PerformanceMetrics:
    ingestion_time_ms: float
    query_latency: LatencyStats
    embedding_call_count: int
    llm_call_count: int
    storage_size_bytes: int
    parse_time_ms: float = 0.0
    embedding_time_ms: float = 0.0
    llm_extraction_time_ms: float = 0.0
    graph_write_time_ms: float = 0.0
    sidecar_write_time_ms: float = 0.0


@dataclass(frozen=True)
class AbGateDecision:
    overall_status: GateStatus
    failed_primary_gates: list[str]
    recommended_fix: str
    recommended_next_block: str


@dataclass(frozen=True)
class ModuleComparison:
    module_code: str
    split: SplitType
    baseline_metrics: EffectivenessMetrics
    candidate_metrics: EffectivenessMetrics
    recall_delta: float
    relation_delta: float
    dimension_delta: float
    passed: bool


@dataclass(frozen=True)
class AbComparisonReport:
    overall_decision: AbGateDecision
    baseline_overall: EffectivenessMetrics
    candidate_overall: EffectivenessMetrics
    per_module: list[ModuleComparison]
    holdout: list[ModuleComparison]
    one_to_n_improved_count: int
    one_to_n_degraded_count: int
    safety: SafetyMetrics
    performance: dict[str, Any]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def latency_stats(measured_runs: list[float], warmup_latency_ms: float | None = None) -> LatencyStats:
    if not measured_runs:
        return LatencyStats(0.0, 0.0, 0.0, 0.0, 0, warmup_latency_ms is not None)
    return LatencyStats(
        median_ms=float(median(measured_runs)),
        p95_ms=percentile(measured_runs, 0.95),
        min_ms=float(min(measured_runs)),
        max_ms=float(max(measured_runs)),
        measured_run_count=len(measured_runs),
        warmup_excluded=warmup_latency_ms is not None,
    )


def to_plain_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, tuple):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain_dict(item) for key, item in value.items()}
    return value
