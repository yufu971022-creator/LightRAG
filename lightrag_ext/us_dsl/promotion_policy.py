from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .candidate_review_report import (
    DECISION_AUTO_ACCEPT,
    DECISION_AUTO_RESOLVE,
    DECISION_INFO_ONLY,
    DECISION_REVIEW_REQUIRED,
)
from .candidate_types import (
    KNOWLEDGE_STATUS_CANDIDATE,
    VALIDATION_INVALID_TYPE,
    VALIDATION_MISSING_EVIDENCE,
    VALIDATION_REVIEW_REQUIRED,
    VALIDATION_VALID,
)
from .kg_schema_policy import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_RELATION_TYPES,
    FORBIDDEN_RELATION_TYPES,
)
from .promotion_types import (
    BLOCKED,
    ELIGIBLE,
    NEEDS_REVIEW,
    OBJECT_KIND_ENTITY,
    OBJECT_KIND_RELATIONSHIP,
    OBJECT_KIND_VERSION_RELATION,
    PromotionCandidate,
)
from .version_relation_types import (
    REL_SUPERSEDES,
    REL_VERSION_CONFLICT,
    REL_VERSION_REVIEW_REQUIRED,
    VERSION_STATUS_REVIEW_REQUIRED,
    VERSION_STATUS_UNKNOWN,
)


APPROVED_BY_REVIEWER = "APPROVED_BY_REVIEWER"
REVIEW_DECISION_VERSION_REVIEW = "VERSION_REVIEW"
REVIEW_DECISION_STRUCTURAL = "STRUCTURAL"
REVIEW_DECISION_EVIDENCE = "EVIDENCE"
STATUS_REVIEW_REQUIRED = "ReviewRequired"
STATUS_INFO_ONLY = "InfoOnly"
STATUS_MISSING_EVIDENCE = "MissingEvidence"
STATUS_VERSION_REVIEW_REQUIRED = "VersionReviewRequired"
STATUS_INVALID_RELATION = "InvalidRelation"
STATUS_INVALID_TYPE = "InvalidType"
STATUS_AUTO_ACCEPTED_FOR_REPORT = "AutoAcceptedForReport"
STATUS_AUTO_ACCEPT_FOR_REPORT = "AutoAcceptForReport"

REQUIRED_EVIDENCE_KEYS = ("sourceUsId", "evidenceText")
TERM_AMBIGUITY_KEYS = ("termReviewRequired", "termAmbiguity", "canonicalTermReviewRequired")


@dataclass(frozen=True)
class PromotionPolicy:
    allowed_entity_types: set[str] = field(default_factory=lambda: set(ALLOWED_ENTITY_TYPES))
    allowed_relation_types: set[str] = field(default_factory=lambda: set(ALLOWED_RELATION_TYPES))
    forbidden_relation_types: set[str] = field(default_factory=lambda: set(FORBIDDEN_RELATION_TYPES))
    allowed_review_decisions: set[str] = field(
        default_factory=lambda: {
            DECISION_AUTO_ACCEPT,
            DECISION_AUTO_RESOLVE,
            APPROVED_BY_REVIEWER,
        }
    )
    reviewer_required_for_confirmed: bool = True
    allow_low_risk_auto_proposal: bool = True
    formal_graph_enabled: bool = False
    candidate_like_knowledge_statuses: set[str] = field(
        default_factory=lambda: {
            KNOWLEDGE_STATUS_CANDIDATE,
            STATUS_AUTO_ACCEPTED_FOR_REPORT,
            STATUS_AUTO_ACCEPT_FOR_REPORT,
        }
    )


def evaluate_candidate_against_policy(
    candidate: PromotionCandidate,
    *,
    policy: PromotionPolicy,
) -> tuple[str, list[str], str | None]:
    reasons: list[str] = []
    metadata = _metadata(candidate)

    if candidate.knowledge_status not in policy.candidate_like_knowledge_statuses:
        reasons.append("KNOWLEDGE_STATUS_NOT_CANDIDATE")
    if candidate.validation_status != VALIDATION_VALID:
        reasons.append(_validation_reason(candidate.validation_status))
    if candidate.review_decision not in policy.allowed_review_decisions:
        reasons.append(_review_decision_reason(candidate.review_decision))
    reasons.extend(_metadata_blockers(metadata))
    reasons.extend(_evidence_blockers(candidate.evidence))

    if candidate.object_kind == OBJECT_KIND_ENTITY:
        reasons.extend(_entity_blockers(candidate, policy=policy))
    elif candidate.object_kind in {OBJECT_KIND_RELATIONSHIP, OBJECT_KIND_VERSION_RELATION}:
        reasons.extend(_relation_blockers(candidate, policy=policy))
    else:
        reasons.append("UNSUPPORTED_OBJECT_KIND")

    if reasons:
        status = BLOCKED if _has_hard_blocker(reasons) else NEEDS_REVIEW
        action = _review_action(status, reasons)
        return status, _dedupe(reasons), action
    return ELIGIBLE, [], "REVIEWER_APPROVAL_REQUIRED"


def has_complete_evidence(evidence: dict[str, Any]) -> bool:
    if any(_is_blank(evidence.get(key)) for key in REQUIRED_EVIDENCE_KEYS):
        return False
    has_text_unit = not _is_blank(evidence.get("textUnitId")) or not _is_blank(
        evidence.get("source_id")
    )
    has_span_or_hash = not _is_blank(evidence.get("sourceSpan")) or not _is_blank(
        evidence.get("textHash")
    )
    return has_text_unit and has_span_or_hash


def is_explicit_supersedes(candidate: PromotionCandidate) -> bool:
    metadata = _metadata(candidate)
    if metadata.get("reasonCode") == "EXPLICIT_SUPERSEDES_EVIDENCE":
        return True
    if metadata.get("explicitSupersedesEvidence") is True:
        return True
    if metadata.get("supersededVersion"):
        return True
    return False


def _entity_blockers(candidate: PromotionCandidate, *, policy: PromotionPolicy) -> list[str]:
    reasons: list[str] = []
    if candidate.proposed_entity_type not in policy.allowed_entity_types:
        reasons.append("INVALID_ENTITY_TYPE")
    if candidate.proposed_entity_type == "RuleVersion":
        status = _string(candidate.version_metadata.get("versionStatus"))
        if status in {"", VERSION_STATUS_UNKNOWN, VERSION_STATUS_REVIEW_REQUIRED}:
            reasons.append("VERSION_STATUS_UNCERTAIN")
    return reasons


def _relation_blockers(candidate: PromotionCandidate, *, policy: PromotionPolicy) -> list[str]:
    reasons: list[str] = []
    relation_type = candidate.proposed_relation_type
    relation_lower = _string(relation_type).lower()
    if relation_lower in policy.forbidden_relation_types:
        reasons.append("FORBIDDEN_RELATION_TYPE")
    if relation_type not in policy.allowed_relation_types:
        reasons.append("INVALID_RELATION_TYPE")
    if not candidate.src_id or not candidate.tgt_id:
        reasons.append("MISSING_RELATION_ENDPOINT")
    if candidate.object_kind == OBJECT_KIND_VERSION_RELATION:
        reasons.extend(_version_relation_blockers(candidate))
    return reasons


def _version_relation_blockers(candidate: PromotionCandidate) -> list[str]:
    reasons: list[str] = []
    relation_type = candidate.proposed_relation_type
    status = _string(candidate.version_metadata.get("versionStatus"))
    if relation_type in {REL_VERSION_REVIEW_REQUIRED, REL_VERSION_CONFLICT}:
        reasons.append("VERSION_RELATION_REQUIRES_REVIEW")
    if status in {"", VERSION_STATUS_UNKNOWN, VERSION_STATUS_REVIEW_REQUIRED}:
        reasons.append("VERSION_STATUS_UNCERTAIN")
    if relation_type == REL_SUPERSEDES and not is_explicit_supersedes(candidate):
        reasons.append("SUPERSEDES_REQUIRES_EXPLICIT_EVIDENCE")
    return reasons


def _metadata_blockers(metadata: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    tokens = {
        _string(metadata.get("knowledgeStatus")),
        _string(metadata.get("reviewDecision")),
        _string(metadata.get("validationStatus")),
        _string(metadata.get("reasonCode")),
    }
    if DECISION_INFO_ONLY in tokens or STATUS_INFO_ONLY in tokens:
        reasons.append("INFO_ONLY_BLOCKED")
    if DECISION_REVIEW_REQUIRED in tokens or STATUS_REVIEW_REQUIRED in tokens:
        reasons.append("REVIEW_REQUIRED_BLOCKED")
    if VALIDATION_MISSING_EVIDENCE in tokens or STATUS_MISSING_EVIDENCE in tokens:
        reasons.append("MISSING_EVIDENCE")
    if VALIDATION_INVALID_TYPE in tokens or STATUS_INVALID_TYPE in tokens:
        reasons.append("INVALID_TYPE")
    if VALIDATION_REVIEW_REQUIRED in tokens:
        reasons.append("VALIDATION_REVIEW_REQUIRED")
    if STATUS_VERSION_REVIEW_REQUIRED in tokens or metadata.get("requiresHumanReview") is True:
        reasons.append("VERSION_REVIEW_REQUIRED_BLOCKED")
    if STATUS_INVALID_RELATION in tokens:
        reasons.append("INVALID_RELATION")
    if any(metadata.get(key) is True for key in TERM_AMBIGUITY_KEYS):
        reasons.append("TERM_AMBIGUITY_REQUIRES_REVIEW")
    return reasons


def _evidence_blockers(evidence: dict[str, Any]) -> list[str]:
    return [] if has_complete_evidence(evidence) else ["MISSING_EVIDENCE"]


def _validation_reason(validation_status: str | None) -> str:
    if validation_status == VALIDATION_MISSING_EVIDENCE:
        return "MISSING_EVIDENCE"
    if validation_status == VALIDATION_INVALID_TYPE:
        return "INVALID_TYPE"
    if validation_status == VALIDATION_REVIEW_REQUIRED:
        return "VALIDATION_REVIEW_REQUIRED"
    if validation_status in (None, ""):
        return "MISSING_VALIDATION_STATUS"
    return "VALIDATION_NOT_VALID"


def _review_decision_reason(review_decision: str | None) -> str:
    if review_decision == DECISION_INFO_ONLY:
        return "INFO_ONLY_BLOCKED"
    if review_decision == DECISION_REVIEW_REQUIRED:
        return "REVIEW_REQUIRED_BLOCKED"
    if review_decision == REVIEW_DECISION_VERSION_REVIEW:
        return "VERSION_REVIEW_REQUIRED_BLOCKED"
    if review_decision in {REVIEW_DECISION_STRUCTURAL, REVIEW_DECISION_EVIDENCE}:
        return "STRUCTURAL_OR_EVIDENCE_ONLY_BLOCKED"
    if review_decision in (None, ""):
        return "MISSING_REVIEW_DECISION"
    return "REVIEW_DECISION_NOT_APPROVABLE"


def _has_hard_blocker(reasons: list[str]) -> bool:
    hard_prefixes = {
        "MISSING_EVIDENCE",
        "INVALID_TYPE",
        "INVALID_RELATION",
        "FORBIDDEN_RELATION_TYPE",
        "SUPERSEDES_REQUIRES_EXPLICIT_EVIDENCE",
        "INFO_ONLY_BLOCKED",
        "REVIEW_REQUIRED_BLOCKED",
        "VERSION_REVIEW_REQUIRED_BLOCKED",
        "VERSION_RELATION_REQUIRES_REVIEW",
    }
    return any(reason in hard_prefixes for reason in reasons)


def _review_action(status: str, reasons: list[str]) -> str:
    if status == BLOCKED:
        return "FIX_BLOCKERS_BEFORE_REVIEW"
    if any(reason.startswith("VERSION") for reason in reasons):
        return "VERSION_REVIEW_REQUIRED"
    return "REVIEWER_APPROVAL_REQUIRED"


def _metadata(candidate: PromotionCandidate) -> dict[str, Any]:
    return dict(candidate.source_object.get("metadata") or {})


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _string(value: Any) -> str:
    return "" if value is None else str(value)


__all__ = [
    "APPROVED_BY_REVIEWER",
    "PromotionPolicy",
    "REQUIRED_EVIDENCE_KEYS",
    "evaluate_candidate_against_policy",
    "has_complete_evidence",
    "is_explicit_supersedes",
]
