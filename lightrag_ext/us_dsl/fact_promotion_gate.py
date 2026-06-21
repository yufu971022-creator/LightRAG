from __future__ import annotations

from .design_quality_types import FunctionalQAResult, ImpactAnalysisResult, QualityGateResult

_BLOCKED_KINDS = {"ISSUE", "CANDIDATE", "INFO_ONLY", "MISSING_EVIDENCE", "INVALID_TYPE", "INVALID_RELATION", "GENERIC_ONLY", "VERSION_REVIEW_REQUIRED"}


def evaluate_fact_promotion(output: FunctionalQAResult | ImpactAnalysisResult) -> QualityGateResult:
    issue = candidate = info = generic = generic_ner = 0
    for fact in getattr(output, "supporting_facts", []):
        if fact.fact_kind == "ISSUE":
            issue += 1
        if fact.fact_kind in {"CANDIDATE", "VERSION_REVIEW_REQUIRED"} and fact.certainty == "CONFIRMED":
            candidate += 1
        if fact.fact_kind == "INFO_ONLY":
            info += 1
        if fact.fact_kind == "GENERIC_ONLY" and fact.certainty == "CONFIRMED":
            generic += 1
        if fact.fact_kind == "GENERIC_NER" and fact.certainty == "CONFIRMED":
            generic_ner += 1
    for item in [*getattr(output, "direct_impacts", []), *getattr(output, "indirect_impacts", []), *getattr(output, "tentative_impacts", [])]:
        if item.candidate_kind == "ISSUE" and item.certainty in {"CONFIRMED", "SUPPORTED"}:
            issue += 1
        if item.candidate_kind == "CANDIDATE" and item.certainty == "CONFIRMED":
            candidate += 1
        if item.candidate_kind == "INFO_ONLY" and item.certainty in {"CONFIRMED", "SUPPORTED"}:
            info += 1
        if item.candidate_kind == "GENERIC_ONLY" and item.certainty == "CONFIRMED":
            generic += 1
        if item.candidate_kind == "GENERIC_NER" and item.certainty == "CONFIRMED":
            generic_ner += 1
    errors = []
    if any([issue, candidate, info, generic, generic_ner]):
        errors.append("UNSAFE_FACT_PROMOTION")
    return QualityGateResult(
        "FACT_PROMOTION",
        not errors,
        errors,
        {
            "issue_as_fact_count": issue,
            "candidate_as_confirmed_count": candidate,
            "info_only_as_fact_count": info,
            "generic_only_as_confirmed_count": generic,
            "generic_ner_fact_hit_count": generic_ner,
        },
        errors,
    )


def blocked_fact_kinds() -> set[str]:
    return set(_BLOCKED_KINDS)
