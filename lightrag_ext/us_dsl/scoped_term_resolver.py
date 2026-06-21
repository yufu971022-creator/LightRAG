from __future__ import annotations

from .term_lexical_normalizer import normalize_term
from .term_normalization_types import TermMappingRecord, TermNormalizationConfig, TermNormalizationDecision, TermScope
from .term_registry import TermRegistry, scope_matches

_SCOPE_PRIORITY = [
    ("module_code", "domain_code", "feature_key", "object_type"),
    ("module_code", "domain_code", "object_type"),
    ("module_code", "feature_key", "object_type"),
    ("module_code", "object_type"),
    ("domain_code", "object_type"),
    ("object_type",),
    tuple(),
]


def resolve_term(
    term: str,
    *,
    scope: TermScope | None,
    registry: TermRegistry,
    config: TermNormalizationConfig | None = None,
) -> TermNormalizationDecision:
    config = config or TermNormalizationConfig()
    query_scope = (scope or TermScope()).normalized()
    lexical = normalize_term(term)
    candidates = [record for record in registry.find_by_source_lexical_key(lexical.lexical_key) if scope_matches(record.scope, query_scope)]
    if not candidates:
        return TermNormalizationDecision(
            original_term=term,
            lexically_normalized_term=lexical.normalized_term,
            canonical_term=term,
            canonical_key=lexical.lexical_key,
            semantic_scope_key=query_scope.semantic_scope_key(),
            decision="NO_MAPPING",
            mapping_status=None,
            mapping_source=None,
            confidence=0.0,
            requires_review=False,
            reason_codes=["no_registry_mapping"],
        )
    ranked = sorted(candidates, key=lambda record: (_priority(record, query_scope), record.term_mapping_id))
    best_priority = _priority(ranked[0], query_scope)
    best = [record for record in ranked if _priority(record, query_scope) == best_priority]
    confirmed = [record for record in best if record.status == "CONFIRMED"]
    confirmed_keys = {record.canonical_key for record in confirmed}
    if len(confirmed_keys) > 1:
        return _decision(
            term=term,
            lexical_term=lexical.normalized_term,
            canonical_term=term,
            canonical_key=lexical.lexical_key,
            scope=query_scope,
            decision="CONFLICT",
            records=best,
            conflicts=confirmed,
            confidence=0.0,
            requires_review=True,
            reason_codes=["term_ambiguity", "conflicting_confirmed_mapping"],
        )
    selected = confirmed[0] if confirmed else best[0]
    if selected.status == "REJECTED":
        return _decision(
            term=term,
            lexical_term=lexical.normalized_term,
            canonical_term=term,
            canonical_key=lexical.lexical_key,
            scope=query_scope,
            decision="REJECTED_MAPPING",
            records=[selected],
            conflicts=[],
            confidence=selected.confidence,
            requires_review=False,
            reason_codes=["mapping_rejected"],
        )
    if selected.status == "CANDIDATE" or selected.confidence < config.auto_confirm_threshold:
        return _decision(
            term=term,
            lexical_term=lexical.normalized_term,
            canonical_term=selected.canonical_term,
            canonical_key=selected.canonical_key,
            scope=query_scope,
            decision="CANDIDATE_REVIEW" if selected.confidence >= config.candidate_threshold else "NO_MAPPING",
            records=[selected],
            conflicts=[],
            confidence=min(selected.confidence, config.auto_confirm_threshold - 0.01),
            requires_review=selected.confidence >= config.candidate_threshold,
            reason_codes=["candidate_mapping_requires_review" if selected.confidence >= config.candidate_threshold else "below_candidate_threshold"],
        )
    if selected.requires_scope and not _has_required_query_scope(selected, query_scope):
        return _decision(
            term=term,
            lexical_term=lexical.normalized_term,
            canonical_term=selected.canonical_term,
            canonical_key=selected.canonical_key,
            scope=query_scope,
            decision="CANDIDATE_REVIEW",
            records=[selected],
            conflicts=[],
            confidence=min(selected.confidence, config.auto_confirm_threshold - 0.01),
            requires_review=True,
            reason_codes=["mapping_requires_scope"],
        )
    decision = "IDENTITY" if selected.source_lexical_key == selected.canonical_key else "REGISTRY_CONFIRMED"
    if selected.synonym_type in {"CASE_VARIANT", "WHITESPACE_VARIANT", "PUNCTUATION_VARIANT"} and selected.source_lexical_key != selected.canonical_key:
        decision = "AUTO_NORMALIZED"
    return _decision(
        term=term,
        lexical_term=lexical.normalized_term,
        canonical_term=selected.canonical_term,
        canonical_key=selected.canonical_key,
        scope=query_scope,
        decision=decision,
        records=[selected],
        conflicts=[],
        confidence=selected.confidence,
        requires_review=False,
        reason_codes=["confirmed_registry_mapping"],
    )


def _priority(record: TermMappingRecord, query_scope: TermScope) -> int:
    scope = record.scope.normalized()
    non_empty = {field for field in ("module_code", "domain_code", "feature_key", "object_type") if getattr(scope, field)}
    for index, fields in enumerate(_SCOPE_PRIORITY, start=1):
        field_set = set(fields)
        if non_empty == field_set and all(getattr(scope, field) == getattr(query_scope, field) for field in field_set):
            return index
    if not non_empty:
        return 7
    return 100 - len(non_empty)


def _has_required_query_scope(record: TermMappingRecord, query_scope: TermScope) -> bool:
    for field in ("module_code", "domain_code", "feature_key", "object_type"):
        if getattr(record.scope, field) and not getattr(query_scope, field):
            return False
    return any(getattr(query_scope, field) for field in ("module_code", "domain_code", "feature_key", "object_type"))


def _decision(
    *,
    term: str,
    lexical_term: str,
    canonical_term: str,
    canonical_key: str,
    scope: TermScope,
    decision: str,
    records: list[TermMappingRecord],
    conflicts: list[TermMappingRecord],
    confidence: float,
    requires_review: bool,
    reason_codes: list[str],
) -> TermNormalizationDecision:
    selected = records[0] if records else None
    return TermNormalizationDecision(
        original_term=term,
        lexically_normalized_term=lexical_term,
        canonical_term=canonical_term,
        canonical_key=canonical_key,
        semantic_scope_key=scope.semantic_scope_key(),
        decision=decision,  # type: ignore[arg-type]
        mapping_status=selected.status if selected else None,
        mapping_source=selected.mapping_source if selected else None,
        confidence=confidence,
        matched_mapping_ids=[record.term_mapping_id for record in records],
        conflict_mapping_ids=[record.term_mapping_id for record in conflicts],
        requires_review=requires_review,
        reason_codes=reason_codes,
    )
