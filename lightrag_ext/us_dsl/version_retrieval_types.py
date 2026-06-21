from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

VersionQueryIntent = Literal["CURRENT", "HISTORICAL", "COMPARE", "MIGRATION", "AS_OF_TIME", "UNSPECIFIED"]
VersionResolutionStatus = Literal[
    "CONFIRMED_CURRENT",
    "CONFIRMED_HISTORICAL",
    "UNKNOWN_CURRENT",
    "NO_CONFIRMED_CURRENT",
    "MULTIPLE_CURRENT_CONFLICT",
    "MULTIPLE_LATEST_CONFLICT",
    "SUPERSEDES_CHAIN_CONFLICT",
    "EVIDENCE_CONFLICT",
    "VERSION_REVIEW_REQUIRED",
    "AS_OF_MATCH",
    "AS_OF_NO_MATCH",
    "VALID_TIME_OVERLAP",
]


@dataclass(frozen=True)
class VersionQueryRequest:
    query_text: str
    explicit_intent: VersionQueryIntent | None = None
    as_of_time: str | None = None
    include_historical: bool = False
    include_unknown: bool = True
    require_confirmed_current: bool = False
    module_code: str | None = None
    domain_code: str | None = None
    feature_key: str | None = None
    object_type: str | None = None
    semantic_object_id: str | None = None
    version_group_key: str | None = None


@dataclass(frozen=True)
class VersionCandidate:
    semantic_object_id: str
    semantic_relation_id: str | None
    version_group_key: str
    version_member_id: str
    rule_version: str | None
    version_status: str | None
    latest_flag: bool | None
    valid_from: str | None
    valid_to: str | None
    supersedes_member_id: str | None
    document_id: str
    document_version_id: str
    document_version_status: str | None
    source_us_id: str | None
    text_unit_id: str | None
    source_span: dict[str, int] = field(default_factory=dict)
    text_hash: str | None = None
    evidence_excerpt: str | None = None
    knowledge_status: str | None = None
    review_decision: str | None = None
    issue_types: list[str] = field(default_factory=list)
    active_contribution: bool = True
    semantic_relevance_score: float = 0.0
    evidence_quality_score: float = 0.0
    stable_identity_key: str | None = None


@dataclass(frozen=True)
class VersionIssueRecord:
    issue_id: str
    version_group_key: str
    semantic_object_id: str | None
    semantic_relation_id: str | None
    issue_type: str
    severity: str
    reason_code: str
    member_ids: list[str] = field(default_factory=list)
    document_version_ids: list[str] = field(default_factory=list)
    source_us_ids: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    review_required: bool = True
    issue_status: str = "OPEN"
    created_at: str = ""


@dataclass(frozen=True)
class CurrentVersionResolution:
    version_group_key: str | None
    resolution_status: VersionResolutionStatus
    current_candidate_id: str | None
    selected_candidates: list[VersionCandidate]
    supporting_candidates: list[VersionCandidate]
    excluded_candidates: list[VersionCandidate]
    issues: list[VersionIssueRecord]
    warnings: list[str]
    safe_for_deterministic_answer: bool
    explanation: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RankedVersionCandidate:
    candidate: VersionCandidate
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VersionAwareRetrievalResult:
    request: VersionQueryRequest
    intent: VersionQueryIntent
    version_group_key: str | None
    resolution_status: VersionResolutionStatus
    selected_candidates: list[VersionCandidate]
    supporting_candidates: list[VersionCandidate]
    historical_candidates: list[VersionCandidate]
    uncertain_candidates: list[VersionCandidate]
    excluded_candidates: list[VersionCandidate]
    version_issues: list[VersionIssueRecord]
    warnings: list[str]
    current_candidate_id: str | None
    ranking_explanation: list[dict[str, Any]]
    evidence_summary: list[dict[str, Any]]
    safe_for_deterministic_answer: bool


@dataclass(frozen=True)
class VersionContext:
    intent: VersionQueryIntent
    resolution_status: VersionResolutionStatus
    safe_for_deterministic_answer: bool
    current_summary: str
    historical_summary: str
    comparison_summary: str
    uncertainty_summary: str
    version_warnings: list[str]
    selected_evidence: list[dict[str, Any]]
    candidate_table: list[dict[str, Any]]
    recommended_answer_behavior: str


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
