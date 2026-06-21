from __future__ import annotations

from .design_quality_types import FunctionalQAResult, ImpactAnalysisResult, QualityGateResult


def evaluate_term_identity(output: FunctionalQAResult | ImpactAnalysisResult) -> QualityGateResult:
    context = getattr(output, "term_identity_context", {}) or {}
    groups = context.get("confirmed_alias_groups", [])
    aliases: dict[str, str] = {}
    split_count = 0
    incorrect_merge_count = 0
    for group in groups:
        identity = group.get("stable_identity_key")
        for alias in group.get("aliases", []):
            previous = aliases.get(alias)
            if previous and previous != identity:
                split_count += 1
            aliases[alias] = identity
        if group.get("generic_without_scope_promoted"):
            incorrect_merge_count += 1
    candidate_aliases = set(context.get("candidate_aliases", []))
    candidate_as_fact = 0
    for fact in getattr(output, "supporting_facts", []):
        if fact.object_id_or_value in candidate_aliases or fact.subject_id in candidate_aliases:
            candidate_as_fact += 1
        if fact.fact_kind == "CANDIDATE_ALIAS":
            candidate_as_fact += 1
    errors = []
    if incorrect_merge_count:
        errors.append("INCORRECT_TERM_MERGE")
    if candidate_as_fact:
        errors.append("CANDIDATE_ALIAS_AS_FACT")
    return QualityGateResult(
        "TERM_IDENTITY",
        not errors,
        errors,
        {
            "term_identity_split_count": split_count,
            "incorrect_term_merge_count": incorrect_merge_count,
            "candidate_alias_as_fact_count": candidate_as_fact,
        },
        errors,
    )
