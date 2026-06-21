from __future__ import annotations

from .design_quality_types import FunctionalQAResult, ImpactAnalysisResult, QualityGateResult


def evaluate_insufficient_evidence(output: FunctionalQAResult | ImpactAnalysisResult) -> QualityGateResult:
    has_direct_evidence = bool(output.source_citations)
    only_unsafe_warnings = any(item.get("kind") in {"issue", "candidate", "generic_only"} for item in output.issues_and_warnings)
    version_unknown = output.version_context.get("resolution_status") not in {None, "CONFIRMED_CURRENT"}
    if isinstance(output, FunctionalQAResult):
        forced = not has_direct_evidence and output.answer_status not in {"INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"}
        unsafe_version = version_unknown and output.answer_status != "ANSWERED_WITH_VERSION_WARNING"
    else:
        forced = not has_direct_evidence and output.safe_for_business_use and output.scenario != "ZERO_TO_ONE"
        unsafe_version = version_unknown and not output.version_context.get("version_warnings")
    errors = []
    if forced:
        errors.append("INSUFFICIENT_EVIDENCE_NOT_REPORTED")
    if only_unsafe_warnings and output.safe_for_business_use:
        errors.append("UNSAFE_CONTEXT_MARKED_SAFE")
    if unsafe_version:
        errors.append("MISSING_VERSION_WARNING")
    return QualityGateResult(
        "INSUFFICIENT_EVIDENCE",
        not errors,
        errors,
        {
            "has_direct_evidence": has_direct_evidence,
            "unsafe_context_marked_safe_count": 1 if only_unsafe_warnings and output.safe_for_business_use else 0,
            "insufficient_evidence_detection_error_count": 1 if forced else 0,
        },
        errors,
    )
