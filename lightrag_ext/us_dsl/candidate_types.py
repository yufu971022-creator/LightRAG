from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VALIDATION_VALID = "VALID"
VALIDATION_INVALID_TYPE = "INVALID_TYPE"
VALIDATION_MISSING_EVIDENCE = "MISSING_EVIDENCE"
VALIDATION_REVIEW_REQUIRED = "REVIEW_REQUIRED"
KNOWLEDGE_STATUS_CANDIDATE = "Candidate"


@dataclass(frozen=True)
class CandidateEntity:
    candidate_id: str
    entity_name: str
    entity_type: str
    description: str
    domain_code: str | None
    feature_key: str | None
    source_us_id: str | None
    source_text_unit_id: str | None
    section_type: str | None
    source_span: dict[str, Any] | None
    text_hash: str | None
    evidence_text: str | None
    extraction_run_id: str
    extraction_method: str = "native_extract_entities_dry_run"
    knowledge_status: str = KNOWLEDGE_STATUS_CANDIDATE
    validation_status: str = VALIDATION_REVIEW_REQUIRED
    confidence_score: float = 0.0
    issues: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateRelation:
    candidate_id: str
    source_entity_name: str
    target_entity_name: str
    relation_type: str | None
    relationship_keywords: str
    description: str
    domain_code: str | None
    feature_key: str | None
    source_us_id: str | None
    source_text_unit_id: str | None
    section_type: str | None
    source_span: dict[str, Any] | None
    text_hash: str | None
    evidence_text: str | None
    extraction_run_id: str
    extraction_method: str = "native_extract_entities_dry_run"
    knowledge_status: str = KNOWLEDGE_STATUS_CANDIDATE
    validation_status: str = VALIDATION_REVIEW_REQUIRED
    confidence_score: float = 0.0
    issues: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateExtractionIssue:
    severity: str
    code: str
    message: str
    candidate_id: str | None = None
    source_text_unit_id: str | None = None


__all__ = [
    "CandidateEntity",
    "CandidateExtractionIssue",
    "CandidateRelation",
    "KNOWLEDGE_STATUS_CANDIDATE",
    "VALIDATION_INVALID_TYPE",
    "VALIDATION_MISSING_EVIDENCE",
    "VALIDATION_REVIEW_REQUIRED",
    "VALIDATION_VALID",
]
