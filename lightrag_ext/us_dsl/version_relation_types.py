from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


REL_HAS_VERSION = "HasVersion"
REL_SUPERSEDES = "Supersedes"
REL_VERSION_CONFLICT = "VersionConflictWith"
REL_VERSION_REVIEW_REQUIRED = "VersionReviewRequired"
REL_DEFINES_VERSION = "DefinesVersion"
REL_DERIVED_FROM_VERSION_EVIDENCE = "DerivedFromVersionEvidence"

VERSION_STATUS_CURRENT = "Current"
VERSION_STATUS_HISTORICAL = "Historical"
VERSION_STATUS_DEPRECATED = "Deprecated"
VERSION_STATUS_CANDIDATE = "Candidate"
VERSION_STATUS_REVIEW_REQUIRED = "ReviewRequired"
VERSION_STATUS_UNKNOWN = "Unknown"
VERSION_STATUS_SINGLE_VERSION_NO_CONFLICT = "SingleVersionNoConflict"
VERSION_STATUS_CURRENT_BY_SINGLE_EVIDENCE_FOR_TEST = "CurrentBySingleEvidenceForTest"


@dataclass(frozen=True)
class VersionedSemanticObject:
    version_group_key: str
    module_code: str | None
    domain_code: str | None
    feature_key: str | None
    object_type: str
    object_key: str
    rule_dimension: str | None
    source_us_id: str | None
    source_text_unit_id: str | None
    section_type: str | None
    evidence_text: str | None
    source_span: dict[str, Any] | None
    text_hash: str | None
    rule_text: str | None
    latest_flag: bool | None
    version_status: str | None
    rule_version: str | None
    supersedes: list[str] = field(default_factory=list)
    version_keywords: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuleVersionNode:
    version_id: str
    version_group_key: str
    version_label: str
    source_us_id: str | None
    source_text_unit_id: str | None
    rule_version: str | None
    latest_flag: bool | None
    version_status: str
    evidence_text: str | None
    source_span: dict[str, Any] | None
    text_hash: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VersionRelation:
    src_id: str
    tgt_id: str
    relation_type: str
    description: str
    source_id: str | None
    evidence_text: str | None
    confidence_score: float
    safe_to_auto_accept: bool
    requires_human_review: bool
    reason_code: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VersionCoverageReport:
    versioned_object_count: int
    rule_version_node_count: int
    has_version_count: int
    supersedes_count: int
    version_conflict_count: int
    version_review_required_count: int
    missing_version_group_key_count: int
    missing_evidence_count: int
    unsafe_supersedes_blocked_count: int
    pass_status: str
    issues: list[dict[str, Any]] = field(default_factory=list)


def serialize_version_coverage_report(report: VersionCoverageReport) -> dict[str, Any]:
    return asdict(report)


__all__ = [
    "REL_DEFINES_VERSION",
    "REL_DERIVED_FROM_VERSION_EVIDENCE",
    "REL_HAS_VERSION",
    "REL_SUPERSEDES",
    "REL_VERSION_CONFLICT",
    "REL_VERSION_REVIEW_REQUIRED",
    "RuleVersionNode",
    "VersionCoverageReport",
    "VersionRelation",
    "VersionedSemanticObject",
    "VERSION_STATUS_CANDIDATE",
    "VERSION_STATUS_CURRENT",
    "VERSION_STATUS_DEPRECATED",
    "VERSION_STATUS_HISTORICAL",
    "VERSION_STATUS_REVIEW_REQUIRED",
    "VERSION_STATUS_SINGLE_VERSION_NO_CONFLICT",
    "VERSION_STATUS_UNKNOWN",
    "serialize_version_coverage_report",
]
