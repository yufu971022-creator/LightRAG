from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

UnifiedE2EMode = Literal["DRY_RUN", "LOCAL_ISOLATED", "LOCAL_REAL_MODELS"]
DocumentRoute = Literal["DSL_FULL", "DSL_PARTIAL", "RAW_ONLY", "PARSE_FAILED"]
UnifiedE2EState = Literal[
    "CREATED",
    "PREFLIGHT_VALIDATED",
    "DOCUMENTS_DISCOVERED",
    "PARSING",
    "RAW_EVIDENCE_INDEXED",
    "ROUTED",
    "DSL_COMPILED",
    "SEMANTIC_BRANCH_WRITTEN",
    "SIDECAR_PERSISTED",
    "LIFECYCLE_VALIDATED",
    "QUERY_CONTEXT_READY",
    "FUNCTIONAL_QA_EXECUTED",
    "IMPACT_ANALYSIS_EXECUTED",
    "QUALITY_GATE_CHECKED",
    "COMPLETED",
    "COMPLETED_WITH_GAPS",
    "FAILED",
    "COMPENSATING",
    "COMPENSATED",
    "CLEANED_UP",
]


@dataclass(frozen=True)
class UnifiedDocumentInput:
    document_id: str
    route: DocumentRoute
    content: str
    source_us_id: str
    parse_should_succeed: bool = True
    version_group_key: str = "vg-generic"


@dataclass(frozen=True)
class UnifiedQueryInput:
    query_id: str
    query_text: str
    scenario: str
    expected_answer_status: str = "ANSWERED_WITH_CONFIRMED_EVIDENCE"


@dataclass(frozen=True)
class UnifiedRequirementInput:
    requirement_id: str
    requirement_text: str
    scenario: str


@dataclass(frozen=True)
class UnifiedE2ERequest:
    run_id: str
    trace_id: str
    mode: UnifiedE2EMode
    document_inputs: list[UnifiedDocumentInput]
    query_inputs: list[UnifiedQueryInput]
    requirement_inputs: list[UnifiedRequirementInput]
    evaluation_case_refs: list[str]
    artifact_root: str
    workspace_root: str
    use_real_embedding: bool = False
    use_real_llm: bool = False
    cleanup_after_run: bool = True
    enable_raw_baseline: bool = True
    enable_dsl_candidate: bool = True
    enable_lifecycle_scenarios: bool = True
    enable_functional_qa: bool = True
    enable_impact_analysis: bool = True
    enable_quality_gate: bool = True
    max_attempts: int = 2
    policy_versions: dict[str, str] = field(default_factory=dict)
    config_versions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentExecutionRecord:
    document_id: str
    document_version_id: str
    route: DocumentRoute
    parse_count: int
    raw_evidence_indexed: bool
    dsl_compiled: bool
    term_normalized_before_identity: bool
    entity_type_resolved_before_identity: bool
    stable_identity_created: bool
    version_governed: bool
    pfss_written: bool
    issue_indexed: bool
    sidecar_persisted: bool
    lifecycle_registered: bool
    completed_with_gap: bool
    failed: bool
    trace_ids: dict[str, str]


@dataclass(frozen=True)
class LifecycleExecutionRecord:
    initial_ingestion_passed: bool
    version_update_passed: bool
    delete_passed: bool
    rebuild_passed: bool
    compensation_passed: bool
    active_version_consistency_passed: bool
    new_supersedes_created: bool = False


@dataclass(frozen=True)
class QueryExecutionRecord:
    query_id: str
    trusted_context_pack_created: bool
    functional_qa_executed: bool
    impact_analysis_executed: bool
    quality_gate_checked: bool
    version_warning_passed: bool
    text_only_fallback_passed: bool
    final_state: str


@dataclass(frozen=True)
class UnifiedE2ERunResult:
    request: UnifiedE2ERequest
    final_business_state: UnifiedE2EState
    final_state: UnifiedE2EState
    documents: list[DocumentExecutionRecord]
    lifecycle: LifecycleExecutionRecord
    queries: list[QueryExecutionRecord]
    quality_summary: dict[str, Any]
    consistency_report: dict[str, Any]
    anti_hardcode_report: dict[str, Any]
    safety_check: dict[str, Any]
    trace_events: list[dict[str, Any]]
    state_transitions: list[dict[str, Any]]
    pending_production_gates: dict[str, Any]
    performance_report: dict[str, Any]


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
