from __future__ import annotations

from .local_fullflow_types import LocalDiscoveredDocument, LocalEvaluationCase, LocalFullflowManifest, LocalFullflowPolicy


def build_local_fullflow_manifest(
    documents: list[LocalDiscoveredDocument],
    cases_by_set: dict[str, list[LocalEvaluationCase]],
    *,
    policy: LocalFullflowPolicy | None = None,
) -> LocalFullflowManifest:
    return LocalFullflowManifest(
        evaluation_mode="local_fullflow",
        suite_id="existing_us_local_fullflow_v1",
        documents=documents,
        evaluation_sets=cases_by_set,
        policy=policy or LocalFullflowPolicy(),
    )


def manifest_counts(manifest: LocalFullflowManifest) -> dict[str, int]:
    cases = [case for case_set in manifest.evaluation_sets.values() for case in case_set]
    return {
        "document_count": len(manifest.documents),
        "accepted_document_count": sum(1 for doc in manifest.documents if doc.accepted),
        "valid_case_count": sum(1 for case in cases if case.valid),
        "invalid_case_count": sum(1 for case in cases if not case.valid),
        "impact_case_count": sum(1 for case in cases if case.task_type == "IMPACT_ANALYSIS"),
    }
