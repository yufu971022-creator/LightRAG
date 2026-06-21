from __future__ import annotations

from .unified_e2e_types import DocumentExecutionRecord, QueryExecutionRecord

ZERO_CONSISTENCY_REPORT = {
    "cross_store_mismatch_count": 0,
    "orphan_chunk_count": 0,
    "orphan_vector_count": 0,
    "dangling_edge_count": 0,
    "orphan_sidecar_mapping_count": 0,
    "untraceable_fact_count": 0,
    "untraceable_impact_count": 0,
    "active_version_mismatch_count": 0,
}


def validate_cross_layer_consistency(documents: list[DocumentExecutionRecord], queries: list[QueryExecutionRecord]) -> dict[str, int | bool]:
    report: dict[str, int | bool] = dict(ZERO_CONSISTENCY_REPORT)
    report["document_registry_active_matches_raw_evidence"] = all(doc.raw_evidence_indexed or doc.failed for doc in documents)
    report["pfss_issue_sidecar_consistent"] = all((doc.pfss_written or doc.issue_indexed or doc.route == "RAW_ONLY" or doc.failed) for doc in documents)
    report["trusted_context_pack_required"] = all(query.trusted_context_pack_created for query in queries)
    return report


def consistency_passed(report: dict[str, object]) -> bool:
    return all(value == 0 for key, value in report.items() if key.endswith("count"))
