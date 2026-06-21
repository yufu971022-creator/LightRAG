from __future__ import annotations

from .hybrid_retrieval_types import PathCandidate, PathValidationReport, RetrievalTaskType

_HOP_LIMITS: dict[RetrievalTaskType, int] = {
    "FACT_QA": 2,
    "TRACEABILITY": 4,
    "IMPACT_ANALYSIS": 5,
    "VERSION_COMPARE": 3,
    "BACKGROUND": 2,
}


def validate_evidence_paths(
    paths: list[PathCandidate],
    *,
    task_type: RetrievalTaskType,
    max_hops: int | None = None,
) -> PathValidationReport:
    limit = max_hops if max_hops is not None else _HOP_LIMITS.get(task_type, 2)
    report = PathValidationReport()
    for path in paths:
        reasons: list[str] = []
        if path.dangling:
            status = "DANGLING_PATH"
            report.dangling_path_count += 1
            reasons.append("dangling")
        elif path.hop_count > limit:
            status = "INVALID_HOP_LIMIT"
            reasons.append(f"hop_limit={limit}")
        elif path.has_issue_edge:
            status = "NOT_FACTUAL_ISSUE_EDGE"
            report.issue_edges_in_factual_path_count += 1
            reasons.append("issue_edge")
        elif path.generic_only:
            status = "BACKGROUND_ONLY"
            report.generic_background_count += 1
            reasons.append("generic_only")
        elif path.version_conflict:
            status = "TENTATIVE_VERSION_CONFLICT"
            reasons.append("version_conflict")
        elif not path.evidence_refs:
            status = "NOT_FACTUAL_MISSING_EVIDENCE"
            report.missing_evidence_factual_path_count += 1
            reasons.append("missing_evidence")
        else:
            status = "FACTUAL"
            reasons.append("complete_evidence")
        path.validation_status = status  # type: ignore[assignment]
        path.validation_reasons = reasons
        report.path_statuses.append(
            {
                "path_id": path.path_id,
                "status": status,
                "hop_count": path.hop_count,
                "reasons": reasons,
            }
        )
    return report
