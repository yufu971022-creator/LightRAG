from __future__ import annotations

from typing import Any


def trace_graph_object_to_evidence(
    repository,
    *,
    graph_space: str,
    graph_namespace: str,
    graph_object_kind: str,
    graph_object_id: str,
) -> dict[str, Any] | None:
    return repository.trace_graph_object(graph_space, graph_namespace, graph_object_kind, graph_object_id)


def document_version_snapshot(repository, document_version_id: str) -> dict[str, Any]:
    return {
        "document_version_id": document_version_id,
        "semantic_objects": repository.list_semantic_objects(document_version_id),
        "semantic_relations": repository.list_semantic_relations(document_version_id),
        "graph_object_mappings": repository.list_graph_mappings(document_version_id),
        "issues": repository.list_issues(document_version_id),
    }


def version_group_readback(repository, version_group_key: str) -> dict[str, Any]:
    return repository.version_group(version_group_key)


def rollback_manifest_readback(repository, batch_id: str) -> list[dict[str, Any]]:
    return repository.get_rollback_manifest(batch_id)


def readback_counts(repository, document_version_id: str, batch_id: str) -> dict[str, int]:
    snapshot = document_version_snapshot(repository, document_version_id)
    return {
        "source_text_units": len(repository.list_source_text_units(document_version_id)),
        "semantic_objects": len(snapshot["semantic_objects"]),
        "semantic_relations": len(snapshot["semantic_relations"]),
        "graph_object_mappings": len(snapshot["graph_object_mappings"]),
        "issues": len(snapshot["issues"]),
        "rollback_records": len(repository.get_rollback_manifest(batch_id)),
    }


def validate_write_readback_counts(repository, expected: dict[str, int]) -> dict[str, Any]:
    counts = repository.record_counts()
    mismatches = {
        key: {"expected": value, "actual": counts.get(key)}
        for key, value in expected.items()
        if counts.get(key) != value
    }
    return {"counts": counts, "mismatches": mismatches, "passed": not mismatches}


def referential_integrity_report(repository) -> dict[str, Any]:
    return repository.validate_referential_integrity()
