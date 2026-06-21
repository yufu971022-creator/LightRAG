from __future__ import annotations

import hashlib
import json

from .document_contribution_registry import stable_chunk_id
from .document_lifecycle_types import DocumentVersionDiff, LifecycleDocumentBundle, MutationOperation, MutationPlan, to_plain_dict

EXTERNAL_WRITE_KINDS = {
    "UPSERT_RAW_CHUNK",
    "DELETE_RAW_CHUNK",
    "UPSERT_CHUNK_VECTOR",
    "DELETE_CHUNK_VECTOR",
    "UPSERT_PFSS_NODE",
    "DELETE_PFSS_NODE",
    "UPSERT_PFSS_EDGE",
    "DELETE_PFSS_EDGE",
    "UPSERT_ENTITY_VECTOR",
    "DELETE_ENTITY_VECTOR",
    "UPSERT_RELATION_VECTOR",
    "DELETE_RELATION_VECTOR",
}

COMPENSATION_BY_KIND = {
    "UPSERT_RAW_CHUNK": "RESTORE_RAW_CHUNK_PREIMAGE",
    "DELETE_RAW_CHUNK": "RESTORE_RAW_CHUNK_PREIMAGE",
    "UPSERT_CHUNK_VECTOR": "RESTORE_CHUNK_VECTOR_PREIMAGE",
    "DELETE_CHUNK_VECTOR": "RESTORE_CHUNK_VECTOR_PREIMAGE",
    "UPSERT_PFSS_NODE": "RESTORE_PFSS_NODE_PREIMAGE",
    "DELETE_PFSS_NODE": "RESTORE_PFSS_NODE_PREIMAGE",
    "UPSERT_PFSS_EDGE": "RESTORE_PFSS_EDGE_PREIMAGE",
    "DELETE_PFSS_EDGE": "RESTORE_PFSS_EDGE_PREIMAGE",
    "UPSERT_ENTITY_VECTOR": "RESTORE_ENTITY_VECTOR_PREIMAGE",
    "DELETE_ENTITY_VECTOR": "RESTORE_ENTITY_VECTOR_PREIMAGE",
    "UPSERT_RELATION_VECTOR": "RESTORE_RELATION_VECTOR_PREIMAGE",
    "DELETE_RELATION_VECTOR": "RESTORE_RELATION_VECTOR_PREIMAGE",
    "ACTIVATE_DOCUMENT_VERSION": "RESTORE_ACTIVE_VERSION_PREIMAGE",
    "DEACTIVATE_DOCUMENT_VERSION": "RESTORE_CONTRIBUTION_PREIMAGE",
    "CREATE_TOMBSTONE": "KEEP_TOMBSTONE_AUDIT_RECORD",
}


def build_upsert_new_version_plan(diff: DocumentVersionDiff) -> MutationPlan:
    operations: list[MutationOperation] = []
    order = 1

    def add(operation_kind: str, store_kind: str, target_kind: str, target_id: str, payload, reason: str) -> None:
        nonlocal order
        operations.append(_op(order, operation_kind, store_kind, target_kind, target_id, payload, reason))
        order += 1

    for item in [*diff.added_chunks, *diff.updated_chunks]:
        add("UPSERT_RAW_CHUNK", "RAW_KV", "raw_chunk", item.stable_id, item.new, "write_new_or_changed_chunk")
    for item in [*diff.added_chunks, *diff.updated_chunks]:
        add("UPSERT_CHUNK_VECTOR", "VECTOR", "chunk_vector", item.stable_id, item.new, "embed_new_or_changed_chunk")
    for item in [*diff.added_semantic_objects, *diff.updated_semantic_objects]:
        add("UPSERT_PFSS_NODE", "PFSS_GRAPH", "semantic_object", item.stable_id, item.new, "write_new_or_changed_node")
    for item in [*diff.added_semantic_objects, *diff.updated_semantic_objects]:
        add("UPSERT_ENTITY_VECTOR", "VECTOR", "entity_vector", item.stable_id, item.new, "embed_new_or_changed_object")
    for item in [*diff.added_semantic_relations, *diff.updated_semantic_relations]:
        add("UPSERT_PFSS_EDGE", "PFSS_GRAPH", "semantic_relation", item.stable_id, item.new, "write_new_or_changed_edge")
    for item in [*diff.added_semantic_relations, *diff.updated_semantic_relations]:
        add("UPSERT_RELATION_VECTOR", "VECTOR", "relation_vector", item.stable_id, item.new, "embed_new_or_changed_relation")
    add("VALIDATE_NEW_PROJECTION", "VALIDATION", "document_version", diff.new_document_version_id or "", None, "validate_before_switch")
    add("ACTIVATE_DOCUMENT_VERSION", "SIDECAR", "document_version", diff.new_document_version_id or "", None, "switch_active_after_validation")
    if diff.old_document_version_id:
        add("DEACTIVATE_DOCUMENT_VERSION", "SIDECAR", "document_version", diff.old_document_version_id, None, "deactivate_old_after_switch")
    for item in diff.removed_semantic_relations:
        add("DELETE_PFSS_EDGE", "PFSS_GRAPH", "semantic_relation", item.stable_id, item.old, "delete_zero_contribution_edge")
        add("DELETE_RELATION_VECTOR", "VECTOR", "relation_vector", item.stable_id, item.old, "delete_zero_contribution_relation_vector")
    for item in diff.removed_semantic_objects:
        add("DELETE_PFSS_NODE", "PFSS_GRAPH", "semantic_object", item.stable_id, item.old, "delete_zero_contribution_node")
        add("DELETE_ENTITY_VECTOR", "VECTOR", "entity_vector", item.stable_id, item.old, "delete_zero_contribution_entity_vector")
    for item in diff.removed_chunks:
        add("DELETE_RAW_CHUNK", "RAW_KV", "raw_chunk", item.stable_id, item.old, "delete_zero_contribution_chunk")
        add("DELETE_CHUNK_VECTOR", "VECTOR", "chunk_vector", item.stable_id, item.old, "delete_zero_contribution_chunk_vector")
    for item in diff.opened_issues:
        add("OPEN_ISSUE", "ISSUE_INDEX", "issue", item.stable_id, item.new, "open_new_issue")
    for item in diff.resolved_issues:
        add("RESOLVE_ISSUE", "ISSUE_INDEX", "issue", item.stable_id, item.old, "resolve_removed_issue")
    return _plan("UPSERT_NEW_VERSION", diff.document_id, diff.old_document_version_id, diff.new_document_version_id, operations)


def build_delete_version_plan(bundle: LifecycleDocumentBundle) -> MutationPlan:
    operations: list[MutationOperation] = []
    order = 1

    def add(operation_kind: str, store_kind: str, target_kind: str, target_id: str, payload, reason: str) -> None:
        nonlocal order
        operations.append(_op(order, operation_kind, store_kind, target_kind, target_id, payload, reason))
        order += 1

    add("DEACTIVATE_DOCUMENT_VERSION", "SIDECAR", "document_version", bundle.document_version_id, None, "delete_version_deactivate_contributions")
    add("ACTIVATE_DOCUMENT_VERSION", "SIDECAR", "document_version", "NO_ACTIVE_VERSION", None, "active_version_deleted_without_restore")
    for rel in sorted(bundle.semantic_relations, key=lambda item: item["semantic_relation_id"]):
        rel_id = str(rel["semantic_relation_id"])
        add("DELETE_PFSS_EDGE", "PFSS_GRAPH", "semantic_relation", rel_id, rel, "delete_zero_contribution_edge")
        add("DELETE_RELATION_VECTOR", "VECTOR", "relation_vector", rel_id, rel, "delete_zero_contribution_relation_vector")
    for obj in sorted(bundle.semantic_objects, key=lambda item: item["semantic_object_id"]):
        obj_id = str(obj["semantic_object_id"])
        add("DELETE_PFSS_NODE", "PFSS_GRAPH", "semantic_object", obj_id, obj, "delete_zero_contribution_node")
        add("DELETE_ENTITY_VECTOR", "VECTOR", "entity_vector", obj_id, obj, "delete_zero_contribution_entity_vector")
    for chunk in sorted(bundle.raw_chunks, key=stable_chunk_id):
        chunk_id = stable_chunk_id(chunk)
        add("DELETE_RAW_CHUNK", "RAW_KV", "raw_chunk", chunk_id, chunk, "delete_zero_contribution_chunk")
        add("DELETE_CHUNK_VECTOR", "VECTOR", "chunk_vector", chunk_id, chunk, "delete_zero_contribution_chunk_vector")
    add("CREATE_TOMBSTONE", "SIDECAR", "document_version", bundle.document_version_id, None, "record_version_tombstone")
    return _plan("DELETE_DOCUMENT_VERSION", bundle.document_id, bundle.document_version_id, None, operations)


def build_delete_document_plan(bundles: list[LifecycleDocumentBundle]) -> MutationPlan:
    if not bundles:
        raise ValueError("delete document requires at least one registered bundle")
    operations: list[MutationOperation] = []
    order = 1

    def add(operation_kind: str, store_kind: str, target_kind: str, target_id: str, payload, reason: str) -> None:
        nonlocal order
        operations.append(_op(order, operation_kind, store_kind, target_kind, target_id, payload, reason))
        order += 1

    for bundle in sorted(bundles, key=lambda item: item.document_version_id):
        add("DEACTIVATE_DOCUMENT_VERSION", "SIDECAR", "document_version", bundle.document_version_id, None, "delete_logical_document_deactivate_version")
    add("ACTIVATE_DOCUMENT_VERSION", "SIDECAR", "document_version", "NO_ACTIVE_VERSION", None, "logical_document_deleted_without_restore")
    rels = _unique_items([rel for bundle in bundles for rel in bundle.semantic_relations], "semantic_relation_id")
    objs = _unique_items([obj for bundle in bundles for obj in bundle.semantic_objects], "semantic_object_id")
    chunks = _unique_chunks([chunk for bundle in bundles for chunk in bundle.raw_chunks])
    for rel in rels:
        rel_id = str(rel["semantic_relation_id"])
        add("DELETE_PFSS_EDGE", "PFSS_GRAPH", "semantic_relation", rel_id, rel, "delete_zero_contribution_edge")
        add("DELETE_RELATION_VECTOR", "VECTOR", "relation_vector", rel_id, rel, "delete_zero_contribution_relation_vector")
    for obj in objs:
        obj_id = str(obj["semantic_object_id"])
        add("DELETE_PFSS_NODE", "PFSS_GRAPH", "semantic_object", obj_id, obj, "delete_zero_contribution_node")
        add("DELETE_ENTITY_VECTOR", "VECTOR", "entity_vector", obj_id, obj, "delete_zero_contribution_entity_vector")
    for chunk in chunks:
        chunk_id = stable_chunk_id(chunk)
        add("DELETE_RAW_CHUNK", "RAW_KV", "raw_chunk", chunk_id, chunk, "delete_zero_contribution_chunk")
        add("DELETE_CHUNK_VECTOR", "VECTOR", "chunk_vector", chunk_id, chunk, "delete_zero_contribution_chunk_vector")
    add("CREATE_TOMBSTONE", "SIDECAR", "logical_document", bundles[0].document_id, None, "record_document_tombstone")
    return _plan("DELETE_LOGICAL_DOCUMENT", bundles[0].document_id, None, None, operations)


def build_rebuild_version_plan(bundle: LifecycleDocumentBundle) -> MutationPlan:
    operations: list[MutationOperation] = []
    order = 1

    def add(operation_kind: str, store_kind: str, target_kind: str, target_id: str, payload, reason: str) -> None:
        nonlocal order
        operations.append(_op(order, operation_kind, store_kind, target_kind, target_id, payload, reason))
        order += 1

    for chunk in sorted(bundle.raw_chunks, key=stable_chunk_id):
        chunk_id = stable_chunk_id(chunk)
        add("UPSERT_RAW_CHUNK", "RAW_KV", "raw_chunk", chunk_id, chunk, "rebuild_raw_projection")
        add("UPSERT_CHUNK_VECTOR", "VECTOR", "chunk_vector", chunk_id, chunk, "rebuild_chunk_vector")
    for obj in sorted(bundle.semantic_objects, key=lambda item: item["semantic_object_id"]):
        obj_id = str(obj["semantic_object_id"])
        add("UPSERT_PFSS_NODE", "PFSS_GRAPH", "semantic_object", obj_id, obj, "rebuild_pfss_node")
        add("UPSERT_ENTITY_VECTOR", "VECTOR", "entity_vector", obj_id, obj, "rebuild_entity_vector")
    for rel in sorted(bundle.semantic_relations, key=lambda item: item["semantic_relation_id"]):
        rel_id = str(rel["semantic_relation_id"])
        add("UPSERT_PFSS_EDGE", "PFSS_GRAPH", "semantic_relation", rel_id, rel, "rebuild_pfss_edge")
        add("UPSERT_RELATION_VECTOR", "VECTOR", "relation_vector", rel_id, rel, "rebuild_relation_vector")
    add("VALIDATE_NEW_PROJECTION", "VALIDATION", "document_version", bundle.document_version_id, None, "validate_rebuild_projection")
    add("ACTIVATE_DOCUMENT_VERSION", "SIDECAR", "document_version", bundle.document_version_id, None, "restore_active_pointer_after_rebuild")
    return _plan("REBUILD_DOCUMENT_VERSION", bundle.document_id, bundle.document_version_id, bundle.document_version_id, operations)


def _op(order: int, operation_kind: str, store_kind: str, target_kind: str, target_id: str, payload, reason: str) -> MutationOperation:
    return MutationOperation(
        operation_id=f"op:{order:04d}:{operation_kind}:{target_id}",
        operation_kind=operation_kind,
        store_kind=store_kind,  # type: ignore[arg-type]
        target_kind=target_kind,
        target_id=target_id,
        reason=reason,
        precondition="public_storage_api_available" if operation_kind in EXTERNAL_WRITE_KINDS else "sidecar_transaction_available",
        preimage=None,
        postimage=payload,
        compensation_operation=COMPENSATION_BY_KIND.get(operation_kind),
        order=order,
    )


def _plan(operation_type: str, document_id: str, old_version_id: str | None, new_version_id: str | None, operations: list[MutationOperation]) -> MutationPlan:
    plan_hash = _plan_hash(operations, operation_type, document_id, old_version_id, new_version_id)
    mutation_id = f"mut:{operation_type.lower()}:{plan_hash[:16]}"
    return MutationPlan(
        mutation_id=mutation_id,
        operation_type=operation_type,  # type: ignore[arg-type]
        document_id=document_id,
        old_document_version_id=old_version_id,
        new_document_version_id=new_version_id,
        operations=operations,
        plan_hash=plan_hash,
    )


def _plan_hash(operations: list[MutationOperation], operation_type: str, document_id: str, old_version_id: str | None, new_version_id: str | None) -> str:
    payload = {
        "operation_type": operation_type,
        "document_id": document_id,
        "old_document_version_id": old_version_id,
        "new_document_version_id": new_version_id,
        "operations": [to_plain_dict(op) for op in operations],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _unique_items(items: list[dict], key: str) -> list[dict]:
    indexed = {str(item[key]): item for item in items}
    return [indexed[item_id] for item_id in sorted(indexed)]


def _unique_chunks(items: list[dict]) -> list[dict]:
    indexed = {stable_chunk_id(item): item for item in items}
    return [indexed[item_id] for item_id in sorted(indexed)]
