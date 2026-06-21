from __future__ import annotations

from .design_quality_types import FunctionalQAResult, ImpactAnalysisResult, QualityGateResult


def evaluate_version_safety(output: FunctionalQAResult | ImpactAnalysisResult) -> QualityGateResult:
    context = output.version_context
    status = context.get("resolution_status", "CONFIRMED_CURRENT")
    warnings = context.get("version_warnings", [])
    version_hard = 0
    historical_as_current = 0
    unsupported_supersedes = 0
    if status != "CONFIRMED_CURRENT" and not warnings and getattr(output, "safe_for_business_use", False):
        version_hard += 1
    for fact in getattr(output, "supporting_facts", []):
        if fact.version_status in {"HISTORICAL", "SUPERSEDED"} and fact.certainty == "CONFIRMED":
            historical_as_current += 1
    for item in [*getattr(output, "direct_impacts", []), *getattr(output, "indirect_impacts", [])]:
        if item.version_status in {"HISTORICAL", "SUPERSEDED"} and item.certainty == "CONFIRMED":
            historical_as_current += 1
    if context.get("supersedes_claimed") and not context.get("supersedes_evidence_refs"):
        unsupported_supersedes += 1
    errors = []
    if version_hard:
        errors.append("VERSION_HARD_JUDGMENT")
    if historical_as_current:
        errors.append("HISTORICAL_AS_CURRENT")
    if unsupported_supersedes:
        errors.append("UNSUPPORTED_SUPERSEDES")
    return QualityGateResult(
        "VERSION_SAFETY",
        not errors,
        errors,
        {
            "version_hard_judgment_error_count": version_hard,
            "historical_as_current_count": historical_as_current,
            "unsupported_supersedes_count": unsupported_supersedes,
            "missing_version_warning_count": 1 if status != "CONFIRMED_CURRENT" and not warnings else 0,
        },
        errors,
    )
