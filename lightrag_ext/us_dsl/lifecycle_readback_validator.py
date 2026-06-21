from __future__ import annotations

from typing import Any

from .document_lifecycle_types import CrossStoreValidationReport, LifecycleDocumentBundle, to_plain_dict
from .lifecycle_storage_adapter import LocalLifecycleStorageAdapter


def validate_cross_store_projection(
    *,
    repository,
    adapter: LocalLifecycleStorageAdapter,
    document_id: str,
    expected_active_version_id: str | None,
) -> CrossStoreValidationReport:
    active = repository.get_active_version(document_id)
    active_version_id = active.get("active_document_version_id") if active else None
    raw_expected = {row["chunk_id"] for row in repository.list_active_contributions("raw_chunk_contributions")}
    object_expected = {row["semantic_object_id"] for row in repository.list_active_contributions("semantic_object_contributions")}
    relation_expected = {row["semantic_relation_id"] for row in repository.list_active_contributions("semantic_relation_contributions")}
    raw_ids = set(adapter.raw_chunks)
    chunk_vector_ids = set(adapter.chunk_vectors)
    node_ids = set(adapter.pfss_nodes)
    edge_ids = set(adapter.pfss_edges)
    entity_vector_ids = set(adapter.entity_vectors)
    relation_vector_ids = set(adapter.relation_vectors)
    raw_match = raw_expected == raw_ids
    vector_match = raw_expected == chunk_vector_ids and object_expected == entity_vector_ids and relation_expected == relation_vector_ids
    pfss_match = object_expected == node_ids and relation_expected == edge_ids
    report = CrossStoreValidationReport(
        active_version_pointer_correct=active_version_id == expected_active_version_id,
        raw_projection_matches_sidecar=raw_match,
        vector_projection_matches_sidecar=vector_match,
        pfss_projection_matches_sidecar=pfss_match,
        dangling_edge_count=adapter.dangling_edge_count(),
        orphan_vector_count=adapter.orphan_vector_count(),
        duplicate_projection_count=adapter.duplicate_projection_count(),
        issue_object_written_to_pfss_count=adapter.issue_object_written_to_pfss_count(),
        passed=(
            active_version_id == expected_active_version_id
            and raw_match
            and vector_match
            and pfss_match
            and adapter.dangling_edge_count() == 0
            and adapter.orphan_vector_count() == 0
            and adapter.duplicate_projection_count() == 0
            and adapter.issue_object_written_to_pfss_count() == 0
        ),
        details={
            "active_version_id": active_version_id,
            "expected_active_version_id": expected_active_version_id,
            "raw_expected": sorted(raw_expected),
            "raw_actual": sorted(raw_ids),
            "object_expected": sorted(object_expected),
            "object_actual": sorted(node_ids),
            "relation_expected": sorted(relation_expected),
            "relation_actual": sorted(edge_ids),
        },
    )
    return report


def active_version_snapshot(repository, document_id: str) -> dict[str, Any]:
    active = repository.get_active_version(document_id)
    return active or {"document_id": document_id, "active_document_version_id": None}


def document_version_lifecycle_snapshot(repository, document_version_id: str) -> dict[str, Any]:
    return {
        "document_version": repository.get_document_version(document_version_id),
        "state_history": repository.list_version_state_history(document_version_id),
        "contributions": repository.list_contributions_for_version(document_version_id),
    }


def expected_projection_from_bundle(bundle: LifecycleDocumentBundle) -> dict[str, list[str]]:
    return {
        "raw_chunks": sorted(str(chunk.get("stable_id") or chunk["chunk_id"]) for chunk in bundle.raw_chunks),
        "semantic_objects": sorted(str(obj["semantic_object_id"]) for obj in bundle.semantic_objects),
        "semantic_relations": sorted(str(rel["semantic_relation_id"]) for rel in bundle.semantic_relations),
    }


def report_to_dict(report: CrossStoreValidationReport) -> dict[str, Any]:
    return to_plain_dict(report)
