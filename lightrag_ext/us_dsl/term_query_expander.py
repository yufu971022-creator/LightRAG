from __future__ import annotations

from .scoped_term_resolver import resolve_term
from .term_normalization_types import TermExpansionResult, TermScope
from .term_registry import TermRegistry, scope_matches


def expand_query_terms(
    query_terms: list[str],
    *,
    module_code: str | None = None,
    domain_code: str | None = None,
    feature_key: str | None = None,
    object_type: str | None = None,
    registry: TermRegistry,
) -> TermExpansionResult:
    scope = TermScope(module_code=module_code, domain_code=domain_code, feature_key=feature_key, object_type=object_type)
    canonical_terms: set[str] = set()
    confirmed_aliases: set[str] = set()
    candidate_aliases: set[str] = set()
    rejected_aliases: set[str] = set()
    ambiguities: list[str] = []
    for term in query_terms:
        decision = resolve_term(term, scope=scope, registry=registry)
        if decision.decision == "CONFLICT":
            ambiguities.append(term)
            continue
        canonical_terms.add(decision.canonical_term)
        for mapping_id in decision.matched_mapping_ids:
            record = registry.by_id(mapping_id)
            if record is None:
                continue
            if record.status == "CONFIRMED":
                confirmed_aliases.add(record.source_term)
            elif record.status == "CANDIDATE":
                candidate_aliases.add(record.source_term)
            elif record.status == "REJECTED":
                rejected_aliases.add(record.source_term)
        for record in registry.aliases_for_canonical_key(decision.canonical_term, scope=scope):
            if not scope_matches(record.scope, scope):
                continue
            if record.status == "CONFIRMED":
                confirmed_aliases.add(record.source_term)
            elif record.status == "CANDIDATE":
                candidate_aliases.add(record.source_term)
            elif record.status == "REJECTED":
                rejected_aliases.add(record.source_term)
    return TermExpansionResult(
        original_terms=query_terms,
        canonical_terms=sorted(canonical_terms),
        confirmed_aliases=sorted(confirmed_aliases),
        candidate_aliases=sorted(candidate_aliases),
        rejected_aliases=sorted(rejected_aliases),
        scope_used=scope.semantic_scope_key(),
        ambiguities=sorted(ambiguities),
        live_query_connected=False,
    )
