from __future__ import annotations

from dataclasses import replace

from .candidate_types import (
    CandidateEntity,
    CandidateRelation,
    VALIDATION_INVALID_TYPE,
    VALIDATION_MISSING_EVIDENCE,
    VALIDATION_REVIEW_REQUIRED,
    VALIDATION_VALID,
)
from .extraction_metrics import detect_relation_type, is_snake_case_relation


def validate_candidate_entity(
    candidate: CandidateEntity,
    allowed_entity_types: list[str],
    *,
    evidence_required: bool = True,
) -> CandidateEntity:
    issues: list[str] = list(candidate.issues)
    allowed = set(allowed_entity_types)
    status = VALIDATION_VALID
    confidence = 0.9

    if evidence_required and _missing_evidence(candidate):
        status = VALIDATION_MISSING_EVIDENCE
        confidence = 0.1
        issues.append("MISSING_EVIDENCE")
    elif candidate.entity_type == "CandidateEntity":
        status = VALIDATION_REVIEW_REQUIRED
        confidence = 0.5
    elif candidate.entity_type not in allowed:
        status = VALIDATION_INVALID_TYPE
        confidence = 0.2
        issues.append("INVALID_ENTITY_TYPE")

    if not candidate.source_span:
        issues.append("SOURCE_SPAN_MISSING")
    if not candidate.feature_key:
        issues.append("MISSING_FEATURE_KEY")
    if not candidate.domain_code:
        issues.append("MISSING_DOMAIN_CODE")

    return replace(
        candidate,
        validation_status=status,
        confidence_score=confidence,
        issues=_stable_unique(issues),
    )


def validate_candidate_relation(
    candidate: CandidateRelation,
    allowed_relation_types: list[str],
    *,
    evidence_required: bool = True,
) -> CandidateRelation:
    issues: list[str] = list(candidate.issues)
    allowed = set(allowed_relation_types)
    relation_type = detect_relation_type(
        candidate.relationship_keywords,
        allowed_relation_types,
    )
    if relation_type is None and candidate.relation_type in allowed:
        relation_type = candidate.relation_type
    if relation_type is None and candidate.relation_type == "CandidateRelation":
        relation_type = "CandidateRelation"

    status = VALIDATION_VALID
    confidence = 0.9
    if evidence_required and _missing_evidence(candidate):
        status = VALIDATION_MISSING_EVIDENCE
        confidence = 0.1
        issues.append("MISSING_EVIDENCE")
    elif relation_type == "CandidateRelation":
        status = VALIDATION_REVIEW_REQUIRED
        confidence = 0.5
    elif relation_type is None:
        status = (
            VALIDATION_INVALID_TYPE
            if is_snake_case_relation(candidate.relationship_keywords)
            else VALIDATION_REVIEW_REQUIRED
        )
        confidence = 0.2 if status == VALIDATION_INVALID_TYPE else 0.5
        issues.append("INVALID_RELATION_TYPE")
    elif relation_type not in allowed:
        status = VALIDATION_INVALID_TYPE
        confidence = 0.2
        issues.append("INVALID_RELATION_TYPE")

    if is_snake_case_relation(candidate.relationship_keywords):
        issues.append("SNAKE_CASE_RELATION")
        if status == VALIDATION_VALID:
            status = VALIDATION_INVALID_TYPE
            confidence = 0.2
    if not candidate.source_span:
        issues.append("SOURCE_SPAN_MISSING")
    if not candidate.feature_key:
        issues.append("MISSING_FEATURE_KEY")
    if not candidate.domain_code:
        issues.append("MISSING_DOMAIN_CODE")

    return replace(
        candidate,
        relation_type=relation_type,
        validation_status=status,
        confidence_score=confidence,
        issues=_stable_unique(issues),
    )


def _missing_evidence(candidate: CandidateEntity | CandidateRelation) -> bool:
    return not candidate.evidence_text or not candidate.source_text_unit_id or not candidate.text_hash


def _stable_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = [
    "validate_candidate_entity",
    "validate_candidate_relation",
]
