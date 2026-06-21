from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

LocalDocumentRole = Literal[
    "CANONICAL_SOURCE",
    "SYNTHETIC_CHANGE_SET",
    "DFX_VARIANT",
    "QUALITY_ANNOTATION",
    "UNKNOWN_SOURCE",
]
LocalCaseSet = Literal["GOLD_BACKED", "SILVER_REGRESSION", "NEGATIVE_QUALITY", "VERSION_STRESS"]
LocalFullflowStatus = Literal[
    "LOCAL_FULLFLOW_PASS",
    "LOCAL_FULLFLOW_PASS_WITH_GAPS",
    "LOCAL_FULLFLOW_FAIL",
    "BLOCKED_NO_LOCAL_US",
    "BLOCKED_ENV",
]


@dataclass(frozen=True)
class LocalDiscoveryPolicy:
    supported_extensions: tuple[str, ...] = (".md", ".txt", ".docx", ".json", ".yaml", ".yml")
    candidate_patterns: tuple[str, ...] = ("us", "userstory", "用户故事", "需求", "设计", "方案", "dfx")
    expected_files: tuple[str, ...] = (
        "LC_Acceptable_Bank_US_v1.md",
        "LC_Acceptable_Bank_66US_with_synthetic_modification_US_for_LightRAG_DSL_test.md",
        "FX_US_优化后全套US_v9.2.docx",
        "FX_US_优化后全套US_v9.2_dfx.docx",
        "FX_US_质检问题高亮版_v9.2.docx",
        "FX_US_质检问题高亮版_v9.2_dfx.docx",
    )


@dataclass(frozen=True)
class LocalDiscoveredDocument:
    document_id: str
    path: str
    file_name: str
    extension: str
    sha256: str
    size_bytes: int
    role: LocalDocumentRole
    accepted: bool
    rejection_reason: str | None = None
    parse_status: str = "NOT_PARSED"
    text_excerpt: str = ""
    detected_us_count: int = 0
    duplicate_of: str | None = None


@dataclass(frozen=True)
class LocalEvaluationCase:
    case_id: str
    document_id: str
    case_set: LocalCaseSet
    task_type: str
    query: str
    source_ref: str
    text_unit_id: str
    evidence_keywords: list[str]
    relation_types: list[str] = field(default_factory=list)
    required_dimensions: list[str] = field(default_factory=list)
    valid: bool = True
    primary_gold: bool = False
    generated_by_llm: bool = False


@dataclass(frozen=True)
class LocalFullflowPolicy:
    minimum_valid_document_count: int = 1
    minimum_valid_case_count: int = 8
    minimum_impact_case_count: int = 2
    max_invalid_citation_count: int = 0
    max_unsupported_factual_path_count: int = 0
    max_version_hard_judgment_error_count: int = 0
    max_generic_ner_fact_hit_count: int = 0
    max_issue_as_fact_count: int = 0
    max_candidate_as_confirmed_count: int = 0
    max_query_p95_latency_ratio: float = 3.0
    max_ingestion_time_ratio: float = 5.0


@dataclass(frozen=True)
class LocalFullflowManifest:
    evaluation_mode: str
    suite_id: str
    documents: list[LocalDiscoveredDocument]
    evaluation_sets: dict[str, list[LocalEvaluationCase]]
    policy: LocalFullflowPolicy


@dataclass(frozen=True)
class LocalPipelineStageResult:
    stage_name: str
    passed: bool
    invoked: bool = True
    records_processed: int = 0
    reason: str = ""


@dataclass(frozen=True)
class LocalGateMetrics:
    baseline_evidence_recall: float
    candidate_evidence_recall: float
    relation_recall_delta: float
    required_dimension_coverage_delta: float
    one_to_n_improved_count: int
    one_to_n_degraded_count: int
    invalid_citation_count: int
    unsupported_factual_path_count: int
    version_hard_judgment_error_count: int
    generic_ner_fact_hit_count: int
    issue_as_fact_count: int
    candidate_as_confirmed_count: int
    ingestion_time_ratio: float
    query_p95_latency_ratio: float
    embedding_call_count: int
    llm_call_count: int
    storage_size_ratio: float


@dataclass(frozen=True)
class LocalFullflowGateResult:
    status: LocalFullflowStatus
    allow_continue_27a_27b_28_local_development: bool
    multi_module_production_gate_pending: bool
    intranet_real_module_validation_pending: bool
    stage_results: list[LocalPipelineStageResult]
    metrics: LocalGateMetrics
    gaps: list[str] = field(default_factory=list)
    failed_gates: list[str] = field(default_factory=list)


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
