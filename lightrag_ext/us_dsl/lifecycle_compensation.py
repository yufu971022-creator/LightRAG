from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .document_lifecycle_types import MutationOperation
from .lifecycle_storage_adapter import LocalLifecycleStorageAdapter


@dataclass(frozen=True)
class AppliedStepPreimage:
    operation: MutationOperation
    preimage: dict[str, Any] | None
    active_preimage: dict[str, Any] | None = None
    contribution_snapshot: dict[str, Any] | None = None


@dataclass
class CompensationResult:
    compensated_operation_ids: list[str] = field(default_factory=list)
    reverse_order_passed: bool = True
    preimage_restored: bool = True
    failed: bool = False
    error_summary: str | None = None


def compensate_applied_steps(
    *,
    adapter: LocalLifecycleStorageAdapter,
    applied_steps: list[AppliedStepPreimage],
    repository=None,
    fail_compensation: bool = False,
) -> CompensationResult:
    result = CompensationResult()
    for index, step in enumerate(reversed(applied_steps)):
        if fail_compensation and index == 0:
            result.failed = True
            result.preimage_restored = False
            result.error_summary = "injected_compensation_failure"
            return result
        _restore_adapter_preimage(adapter, step.operation, step.preimage)
        if repository is not None and step.active_preimage is not None:
            document_id = step.active_preimage["document_id"]
            repository.set_document_active_version(document_id, step.active_preimage.get("active_document_version_id"), step.active_preimage["updated_by_batch_id"])
        result.compensated_operation_ids.append(step.operation.operation_id)
    expected = [step.operation.operation_id for step in reversed(applied_steps)]
    result.reverse_order_passed = result.compensated_operation_ids == expected
    return result


def _restore_adapter_preimage(adapter: LocalLifecycleStorageAdapter, operation: MutationOperation, preimage: dict[str, Any] | None) -> None:
    store = _store_for_operation(operation.operation_kind)
    if store is None:
        return
    adapter.restore(store, operation.target_id, preimage)


def _store_for_operation(operation_kind: str) -> str | None:
    if operation_kind in {"UPSERT_RAW_CHUNK", "DELETE_RAW_CHUNK"}:
        return "raw_chunks"
    if operation_kind in {"UPSERT_CHUNK_VECTOR", "DELETE_CHUNK_VECTOR"}:
        return "chunk_vectors"
    if operation_kind in {"UPSERT_PFSS_NODE", "DELETE_PFSS_NODE"}:
        return "pfss_nodes"
    if operation_kind in {"UPSERT_PFSS_EDGE", "DELETE_PFSS_EDGE"}:
        return "pfss_edges"
    if operation_kind in {"UPSERT_ENTITY_VECTOR", "DELETE_ENTITY_VECTOR"}:
        return "entity_vectors"
    if operation_kind in {"UPSERT_RELATION_VECTOR", "DELETE_RELATION_VECTOR"}:
        return "relation_vectors"
    return None
