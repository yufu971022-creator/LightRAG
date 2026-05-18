from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .candidate_types import CandidateEntity, CandidateRelation
from .config_registry import DEFAULT_CONFIG_REGISTRY


HIGH_RISK_DOMAINS = DEFAULT_CONFIG_REGISTRY.high_risk_domains
HIGH_RISK_SECTIONS = DEFAULT_CONFIG_REGISTRY.high_risk_sections
VERSION_AMBIGUITY_KEYWORDS = DEFAULT_CONFIG_REGISTRY.version_keywords
CRITICAL_TERMS = DEFAULT_CONFIG_REGISTRY.critical_terms


@dataclass(frozen=True)
class CandidateReviewPolicy:
    auto_accept_confidence_threshold: float = 0.75
    low_confidence_threshold: float = 0.5
    max_human_review_ratio: float = 0.20
    warn_human_review_ratio: float = 0.30
    evidence_required: bool = True
    review_invalid_type: bool = True
    review_missing_evidence: bool = True
    review_version_conflict: bool = True
    review_term_ambiguity: bool = True
    high_risk_domains: set[str] = field(default_factory=lambda: set(HIGH_RISK_DOMAINS))
    high_risk_sections: set[str] = field(default_factory=lambda: set(HIGH_RISK_SECTIONS))
    auto_resolve_candidate_relation_if_mapping_available: bool = True
    do_not_review_all_candidates: bool = True


def detect_version_review_required(
    candidate: CandidateEntity | CandidateRelation,
    context: dict[str, Any] | None,
) -> tuple[bool, str]:
    feature_context = _feature_context(context, candidate.feature_key)
    if not feature_context:
        return False, "No version context."

    versions = _versions(feature_context)
    if feature_context.get("latestFlagConflict") is True:
        return True, "latestFlag conflict exists."
    if feature_context.get("ambiguousLatest") is True:
        return True, "Latest rule is ambiguous."
    if feature_context.get("mutuallyExclusiveRules") or feature_context.get("conflicts"):
        if not feature_context.get("supersedes"):
            return True, "Mutually exclusive rules lack supersedes metadata."

    if len(versions) <= 1:
        return False, "Single rule version."

    latest_count = sum(1 for version in versions if version.get("latestFlag") is True)
    if latest_count > 1:
        return True, "Multiple versions are marked latest."
    if latest_count == 1:
        return False, "Unique latest version."

    newer_source_ids = {str(value) for value in feature_context.get("newerSourceUsIds", [])}
    if candidate.source_us_id and candidate.source_us_id in newer_source_ids:
        if not feature_context.get("supersedes"):
            return True, "Candidate source has a newer sourceUsId without supersedes."

    text = f"{candidate.description}\n{candidate.evidence_text or ''}"
    has_version_keyword = any(keyword in text for keyword in VERSION_AMBIGUITY_KEYWORDS)
    if has_version_keyword and not feature_context.get("versionManagement"):
        return True, "Version-sensitive text lacks versionManagement metadata."

    return True, "Multiple versions exist without a unique latest rule."


def detect_term_review_required(
    candidate: CandidateEntity | CandidateRelation,
    synonym_context: dict[str, Any] | None,
) -> tuple[bool, str]:
    if not synonym_context:
        return False, "No synonym context."

    for term in _candidate_terms(candidate):
        matches = _synonym_matches(term, synonym_context)
        if not matches:
            continue
        canonical_values = {
            str(match.get("canonical") or match.get("canonicalTerm") or match.get("term"))
            for match in matches
        }
        confirmed = [
            match
            for match in matches
            if str(match.get("status") or match.get("knowledgeStatus")).lower()
            == "confirmed"
        ]
        if len(canonical_values) == 1 and len(confirmed) == 1:
            continue
        if len(canonical_values) > 1:
            return True, f"Term {term} maps to multiple canonical terms."
        if any(str(match.get("type")) == "CandidateSynonym" for match in matches):
            return True, f"Term {term} depends on CandidateSynonym."
        if term in CRITICAL_TERMS and not confirmed:
            return True, f"Critical term {term} is not confirmed."

    return False, "No ambiguous term mapping."


def _feature_context(
    context: dict[str, Any] | None,
    feature_key: str | None,
) -> dict[str, Any]:
    if not context:
        return {}
    if feature_key and isinstance(context.get(feature_key), dict):
        return dict(context[feature_key])
    features = context.get("features")
    if feature_key and isinstance(features, dict) and isinstance(features.get(feature_key), dict):
        return dict(features[feature_key])
    return dict(context)


def _versions(feature_context: dict[str, Any]) -> list[dict[str, Any]]:
    value = feature_context.get("ruleVersions") or feature_context.get("versions") or []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _candidate_terms(candidate: CandidateEntity | CandidateRelation) -> list[str]:
    if isinstance(candidate, CandidateEntity):
        return [candidate.entity_name]
    return [
        candidate.source_entity_name,
        candidate.target_entity_name,
        candidate.relationship_keywords,
    ]


def _synonym_matches(term: str, synonym_context: dict[str, Any]) -> list[dict[str, Any]]:
    terms = synonym_context.get("terms")
    if isinstance(terms, dict) and isinstance(terms.get(term), list):
        return [dict(item) for item in terms[term] if isinstance(item, dict)]
    value = synonym_context.get(term)
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


__all__ = [
    "CandidateReviewPolicy",
    "detect_term_review_required",
    "detect_version_review_required",
]
