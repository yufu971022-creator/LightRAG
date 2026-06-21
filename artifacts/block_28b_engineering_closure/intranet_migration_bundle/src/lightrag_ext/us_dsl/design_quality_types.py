from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

AnswerStatus = Literal[
    "ANSWERED_WITH_CONFIRMED_EVIDENCE",
    "ANSWERED_WITH_VERSION_WARNING",
    "TEXT_ONLY_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
    "CONFLICTING_EVIDENCE",
    "BLOCKED_BY_UNSAFE_CONTEXT",
]
ImpactLevel = Literal["DIRECT", "INDIRECT", "TENTATIVE"]
Certainty = Literal["CONFIRMED", "SUPPORTED", "POSSIBLE", "UNCONFIRMED"]
QualityState = Literal[
    "OUTPUT_DRAFTED",
    "QUALITY_CHECKING",
    "REPAIR_PLANNED",
    "REPAIR_EXECUTING",
    "QUALITY_GATE_PASSED",
    "QUALITY_GATE_FAILED",
    "INSUFFICIENT_EVIDENCE",
]

RELEVANT_DOMAINS = [
    "MasterData",
    "Workflow",
    "Ledger",
    "RuleManagement",
    "MonitoringReport",
    "Integration",
    "Configuration",
    "AccessAudit",
    "DataMigrationInitialization",
    "Other",
]


@dataclass(frozen=True)
class SourceCitation:
    document_id: str
    document_version_id: str
    source_us_id: str
    text_unit_id: str
    source_span: dict[str, int]
    text_hash: str
    evidence_excerpt: str


@dataclass(frozen=True)
class SupportingFact:
    fact_id: str
    subject_id: str
    predicate: str
    object_id_or_value: str
    fact_text: str
    trust_tier: str
    version_status: str
    evidence_refs: list[str]
    certainty: Certainty
    fact_kind: str = "FACT"
    stable_identity_key: str | None = None


@dataclass(frozen=True)
class ImpactItem:
    impact_id: str
    affected_object_id: str
    affected_object_name: str
    affected_object_type: str
    domain_code: str
    feature_key: str
    impact_type: str
    impact_level: ImpactLevel
    impact_path: list[str]
    relation_types: list[str]
    evidence_refs: list[str]
    version_status: str
    certainty: Certainty
    risk_level: str
    reason: str
    requires_review: bool
    candidate_kind: str = "FACT"


@dataclass(frozen=True)
class QualityGateResult:
    gate_name: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    blocked_reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FunctionalQAResult:
    query: str
    scenario: str
    answer_status: AnswerStatus
    direct_answer: str
    supporting_facts: list[SupportingFact]
    supporting_relations: list[dict[str, Any]]
    supporting_paths: list[dict[str, Any]]
    source_citations: list[SourceCitation]
    version_context: dict[str, Any]
    term_identity_context: dict[str, Any]
    issues_and_warnings: list[dict[str, Any]]
    open_questions: list[dict[str, str]]
    excluded_claims: list[str]
    safe_for_business_use: bool
    quality_gate_result: QualityGateResult | None
    execution_trace: list[dict[str, Any]]


@dataclass(frozen=True)
class ImpactAnalysisResult:
    requirement: str
    scenario: str
    primary_change_targets: list[str]
    direct_impacts: list[ImpactItem]
    indirect_impacts: list[ImpactItem]
    tentative_impacts: list[ImpactItem]
    excluded_candidates: list[ImpactItem]
    domain_coverage: dict[str, Any]
    feature_coverage: dict[str, Any]
    version_context: dict[str, Any]
    source_citations: list[SourceCitation]
    issues_and_warnings: list[dict[str, Any]]
    open_questions: list[dict[str, str]]
    test_scope_hints: list[str]
    safe_for_business_use: bool
    quality_gate_result: QualityGateResult | None
    execution_trace: list[dict[str, Any]]


@dataclass(frozen=True)
class DesignQualityCase:
    case_id: str
    case_set: str
    task_type: str
    scenario: str
    prompt: str
    expected_status: str
    expected_domains: list[str] = field(default_factory=list)
    expected_dimensions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepairAction:
    action_id: str
    action_type: str
    target_gate: str
    reason_code: str
    description: str


@dataclass(frozen=True)
class RepairPlan:
    case_id: str
    attempt_number: int
    actions: list[RepairAction]
    max_attempts: int = 2
    full_chain_rerun_allowed: bool = False


@dataclass(frozen=True)
class QualityHarnessResult:
    case_id: str
    task_type: str
    final_state: QualityState
    attempts_used: int
    initial_gate_results: list[QualityGateResult]
    final_gate_results: list[QualityGateResult]
    repair_plan: RepairPlan | None
    output: FunctionalQAResult | ImpactAnalysisResult
    state_transitions: list[dict[str, Any]]


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
