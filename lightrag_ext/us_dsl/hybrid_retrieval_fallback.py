from __future__ import annotations

from .hybrid_retrieval_types import FallbackResult, PathValidationReport, RetrievalCandidate


def decide_hybrid_retrieval_fallback(
    candidates: list[RetrievalCandidate],
    *,
    strict_scope: bool,
    path_report: PathValidationReport,
) -> FallbackResult:
    if not candidates:
        if strict_scope:
            return FallbackResult("STRICT_SCOPE_EMPTY", False, ["strict_scope_no_result"])
        return FallbackResult("INSUFFICIENT_EVIDENCE", False, ["no_result"])

    has_raw = any(item.channel == "RAW_TEXT" for item in candidates)
    has_direct_evidence = has_raw or any(item.evidence for item in candidates)
    has_pfss = any(item.channel.startswith("PFSS") for item in candidates)
    has_generic = any(item.channel == "GENERIC_GRAPH" for item in candidates)
    has_issue = any(item.channel in {"ISSUE_SIDECAR", "VERSION_CONTEXT"} for item in candidates)
    has_factual_path = any(item["status"] == "FACTUAL" for item in path_report.path_statuses)
    has_version_warning = any(
        item.version_status in {"CONFLICT", "UNKNOWN_CURRENT", "MULTIPLE_CURRENT_CONFLICT"}
        or (item.path is not None and item.path.validation_status == "TENTATIVE_VERSION_CONFLICT")
        for item in candidates
    )

    if has_pfss and has_direct_evidence and has_factual_path and not has_version_warning:
        return FallbackResult("HYBRID_EVIDENCE_READY", True, ["pfss_raw_factual_path"])
    if has_pfss and has_version_warning:
        return FallbackResult("PFSS_WITH_VERSION_WARNING", False, ["version_warning"])
    if has_raw and not has_pfss:
        return FallbackResult("TEXT_ONLY_FALLBACK", False, ["raw_only"])
    if has_issue and not has_pfss and not has_raw:
        return FallbackResult("ISSUE_ONLY", False, ["warning_only"])
    if has_generic and not has_pfss and not has_raw:
        return FallbackResult("GENERIC_ONLY_LOW_TRUST", False, ["generic_only"])
    return FallbackResult("INSUFFICIENT_EVIDENCE", False, ["insufficient_factual_support"])
