from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from .document_contribution_registry import DocumentContributionRegistry, stable_chunk_id
from .document_lifecycle_types import LifecycleDocumentBundle, LifecycleMutationResult, MutationOperation, MutationPlan
from .document_version_diff import build_document_version_diff
from .lifecycle_compensation import AppliedStepPreimage, CompensationResult, compensate_applied_steps
from .lifecycle_storage_adapter import LocalLifecycleStorageAdapter
from .multistore_mutation_plan import (
    build_delete_document_plan,
    build_delete_version_plan,
    build_rebuild_version_plan,
    build_upsert_new_version_plan,
)
from .sidecar_registry_types import IngestionBatchRecord, SidecarPersistenceBundle


@dataclass
class LifecycleServiceResult:
    mutation_result: LifecycleMutationResult
    plan: MutationPlan
    compensation: CompensationResult | None = None
    embedding_before: dict[str, int] = field(default_factory=dict)
    embedding_after: dict[str, int] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


class DocumentLifecycleService:
    def __init__(self, *, repository, adapter: LocalLifecycleStorageAdapter | None = None) -> None:
        self.repository = repository
        self.adapter = adapter or LocalLifecycleStorageAdapter()
        self.registry = DocumentContributionRegistry(repository)
        self.registered_bundles: dict[str, LifecycleDocumentBundle] = {}
        self.document_versions: dict[str, list[str]] = {}
        self.compensation_failure_marks_rebuild_required = False

    def register_initial_version(self, bundle: LifecycleDocumentBundle, *, batch_id: str = "batch-initial") -> None:
        self._ensure_batch(batch_id, trace_id=f"trace:{batch_id}", route="DSL_FULL")
        self._persist_base_bundle(bundle, batch_id=batch_id, status="STAGED")
        self._apply_full_projection(bundle)
        self.registry.register_bundle_contributions(bundle, batch_id=batch_id, active=True)
        self._set_version_state(bundle.document_version_id, "ACTIVE", batch_id, "initial_projection")
        self.repository.set_document_active_version(bundle.document_id, bundle.document_version_id, batch_id)
        self.repository.complete_batch(batch_id, {"operation": "INITIAL_PROJECTION"})
        self._remember_bundle(bundle)

    def upsert_new_version(
        self,
        *,
        old_bundle: LifecycleDocumentBundle,
        new_bundle: LifecycleDocumentBundle,
        batch_id: str = "batch-upsert-new-version",
        fail_after_operation_kind: str | None = None,
        fail_compensation: bool = False,
    ) -> LifecycleServiceResult:
        self._ensure_batch(batch_id, trace_id=f"trace:{batch_id}", route="DSL_FULL")
        self._persist_base_bundle(new_bundle, batch_id=batch_id, status="STAGED", skip_existing_semantic=True)
        self._set_version_state(new_bundle.document_version_id, "STAGED", batch_id, "new_version_staged")
        diff = build_document_version_diff(old_bundle, new_bundle)
        plan = build_upsert_new_version_plan(diff)
        return self._execute_plan(
            plan,
            batch_id=batch_id,
            operation_context={"old_bundle": old_bundle, "new_bundle": new_bundle},
            fail_after_operation_kind=fail_after_operation_kind,
            fail_compensation=fail_compensation,
        )

    def delete_document_version(self, *, bundle: LifecycleDocumentBundle, batch_id: str = "batch-delete-version") -> LifecycleServiceResult:
        self._ensure_batch(batch_id, trace_id=f"trace:{batch_id}", route="DELETE")
        plan = build_delete_version_plan(bundle)
        return self._execute_plan(plan, batch_id=batch_id, operation_context={"delete_bundle": bundle})

    def delete_logical_document(self, *, document_id: str, batch_id: str = "batch-delete-document") -> LifecycleServiceResult:
        bundles = [self.registered_bundles[version_id] for version_id in self.document_versions.get(document_id, [])]
        self._ensure_batch(batch_id, trace_id=f"trace:{batch_id}", route="DELETE")
        plan = build_delete_document_plan(bundles)
        return self._execute_plan(plan, batch_id=batch_id, operation_context={"delete_document_bundles": bundles})

    def rebuild_document_version(self, *, document_version_id: str, batch_id: str = "batch-rebuild-version") -> LifecycleServiceResult:
        bundle = self.registered_bundles[document_version_id]
        self._ensure_batch(batch_id, trace_id=f"trace:{batch_id}", route="REBUILD")
        self.repository.create_rebuild_request(
            {
                "rebuild_request_id": f"rebuild:{document_version_id}:{batch_id}",
                "document_version_id": document_version_id,
                "reason_code": "projection_rebuild_requested",
                "status": "REBUILDING",
                "requested_by_batch_id": batch_id,
            }
        )
        self._set_version_state(document_version_id, "REBUILDING", batch_id, "rebuild_requested")
        plan = build_rebuild_version_plan(bundle)
        result = self._execute_plan(plan, batch_id=batch_id, operation_context={"rebuild_bundle": bundle})
        self._remove_extra_projection_for_bundle(bundle)
        self._set_version_state(document_version_id, "ACTIVE", batch_id, "rebuild_completed")
        return result

    def _execute_plan(
        self,
        plan: MutationPlan,
        *,
        batch_id: str,
        operation_context: dict[str, Any],
        fail_after_operation_kind: str | None = None,
        fail_compensation: bool = False,
    ) -> LifecycleServiceResult:
        embedding_before = self._embedding_counts()
        applied: list[AppliedStepPreimage] = []
        adapter_snapshot = self.adapter.snapshot()
        active_snapshot = self.repository.get_active_version(plan.document_id) or {
            "document_id": plan.document_id,
            "active_document_version_id": None,
            "updated_by_batch_id": batch_id,
        }
        mutation_id = f"{plan.mutation_id}:{batch_id}"
        step_id_by_operation = {op.operation_id: _step_id(mutation_id, op) for op in plan.operations}
        self.repository.create_lifecycle_mutation(
            {
                "mutation_id": mutation_id,
                "batch_id": batch_id,
                "document_id": plan.document_id,
                "old_document_version_id": plan.old_document_version_id,
                "new_document_version_id": plan.new_document_version_id,
                "operation_type": plan.operation_type,
                "status": "PLANNED",
                "plan_hash": plan.plan_hash,
            }
        )
        for op in plan.operations:
            self.repository.insert_lifecycle_step(
                {
                    "mutation_step_id": step_id_by_operation[op.operation_id],
                    "mutation_id": mutation_id,
                    "step_order": op.order,
                    "store_kind": op.store_kind,
                    "operation_kind": op.operation_kind,
                    "target_kind": op.target_kind,
                    "target_id": op.target_id,
                    "preimage": op.preimage,
                    "postimage": op.postimage,
                    "status": "PENDING",
                }
            )
        try:
            self.repository.update_lifecycle_mutation(mutation_id, "APPLYING")
            for op in plan.operations:
                preimage = self._apply_operation(op, batch_id=batch_id, context=operation_context)
                active_preimage = active_snapshot if op.operation_kind == "ACTIVATE_DOCUMENT_VERSION" else None
                applied.append(AppliedStepPreimage(operation=op, preimage=preimage, active_preimage=active_preimage))
                self.repository.update_lifecycle_step(step_id_by_operation[op.operation_id], "APPLIED")
                if fail_after_operation_kind == op.operation_kind:
                    raise RuntimeError(f"injected_failure_after_{op.operation_kind.lower()}")
            self.repository.update_lifecycle_mutation(mutation_id, "APPLIED")
            self.repository.complete_batch(batch_id, {"mutation_id": mutation_id, "plan_hash": plan.plan_hash})
            mutation_result = LifecycleMutationResult(
                mutation_id=mutation_id,
                operation_type=plan.operation_type,
                status="APPLIED",
                plan_hash=plan.plan_hash,
                applied_step_count=len(applied),
                compensated_step_count=0,
            )
            return LifecycleServiceResult(mutation_result=mutation_result, plan=plan, embedding_before=embedding_before, embedding_after=self._embedding_counts())
        except Exception as exc:
            self.repository.update_lifecycle_mutation(mutation_id, "COMPENSATING", {"code": type(exc).__name__, "summary": str(exc)})
            compensation = compensate_applied_steps(adapter=self.adapter, applied_steps=applied, repository=self.repository, fail_compensation=fail_compensation)
            if compensation.failed:
                self.adapter.restore_snapshot(adapter_snapshot)
                self.repository.update_lifecycle_mutation(mutation_id, "FAILED", {"code": "COMPENSATION_FAILED", "summary": compensation.error_summary or "compensation failed"})
                if plan.new_document_version_id:
                    self._set_version_state(plan.new_document_version_id, "REBUILD_REQUIRED", batch_id, "compensation_failed")
                self.compensation_failure_marks_rebuild_required = True
                status = "FAILED"
            else:
                self.adapter.restore_snapshot(adapter_snapshot)
                if plan.operation_type == "UPSERT_NEW_VERSION" and plan.new_document_version_id:
                    self.registry.deactivate_version(plan.new_document_version_id, batch_id=batch_id)
                    self._set_version_state(plan.new_document_version_id, "FAILED", batch_id, "mutation_compensated")
                self.repository.update_lifecycle_mutation(mutation_id, "COMPENSATED")
                status = "COMPENSATED"
            self.repository.fail_batch(batch_id, {"code": type(exc).__name__, "summary": str(exc)})
            mutation_result = LifecycleMutationResult(
                mutation_id=mutation_id,
                operation_type=plan.operation_type,
                status=status,
                plan_hash=plan.plan_hash,
                applied_step_count=len(applied),
                compensated_step_count=len(compensation.compensated_operation_ids),
                error_code=type(exc).__name__,
                error_summary=str(exc),
            )
            return LifecycleServiceResult(
                mutation_result=mutation_result,
                plan=plan,
                compensation=compensation,
                embedding_before=embedding_before,
                embedding_after=self._embedding_counts(),
            )

    def _apply_operation(self, op: MutationOperation, *, batch_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
        if op.operation_kind == "UPSERT_RAW_CHUNK":
            return self.adapter.upsert_raw_chunk(op.postimage or _lookup_payload(op, context))
        if op.operation_kind == "DELETE_RAW_CHUNK":
            if self._can_delete(op):
                return self.adapter.delete_raw_chunk(op.target_id)
            return self.adapter.raw_chunks.get(op.target_id)
        if op.operation_kind == "UPSERT_CHUNK_VECTOR":
            return self.adapter.upsert_chunk_vector(op.postimage or _lookup_payload(op, context))
        if op.operation_kind == "DELETE_CHUNK_VECTOR":
            if self._can_delete(op):
                return self.adapter.delete_chunk_vector(op.target_id)
            return self.adapter.chunk_vectors.get(op.target_id)
        if op.operation_kind == "UPSERT_PFSS_NODE":
            return self.adapter.upsert_pfss_node(op.postimage or _lookup_payload(op, context))
        if op.operation_kind == "DELETE_PFSS_NODE":
            if self._can_delete(op):
                return self.adapter.delete_pfss_node(op.target_id)
            return self.adapter.pfss_nodes.get(op.target_id)
        if op.operation_kind == "UPSERT_PFSS_EDGE":
            return self.adapter.upsert_pfss_edge(op.postimage or _lookup_payload(op, context))
        if op.operation_kind == "DELETE_PFSS_EDGE":
            if self._can_delete(op):
                return self.adapter.delete_pfss_edge(op.target_id)
            return self.adapter.pfss_edges.get(op.target_id)
        if op.operation_kind == "UPSERT_ENTITY_VECTOR":
            return self.adapter.upsert_entity_vector(op.postimage or _lookup_payload(op, context))
        if op.operation_kind == "DELETE_ENTITY_VECTOR":
            if self._can_delete(op):
                return self.adapter.delete_entity_vector(op.target_id)
            return self.adapter.entity_vectors.get(op.target_id)
        if op.operation_kind == "UPSERT_RELATION_VECTOR":
            return self.adapter.upsert_relation_vector(op.postimage or _lookup_payload(op, context))
        if op.operation_kind == "DELETE_RELATION_VECTOR":
            if self._can_delete(op):
                return self.adapter.delete_relation_vector(op.target_id)
            return self.adapter.relation_vectors.get(op.target_id)
        if op.operation_kind == "VALIDATE_NEW_PROJECTION":
            return None
        if op.operation_kind == "ACTIVATE_DOCUMENT_VERSION":
            if op.target_id == "NO_ACTIVE_VERSION":
                self.repository.set_document_active_version(context_document_id(context, op, self), None, batch_id)
            else:
                old_active = self.repository.get_active_version(context_document_id(context, op, self))
                self.repository.set_document_active_version(context_document_id(context, op, self), op.target_id, batch_id)
                if context.get("new_bundle") and op.target_id == context["new_bundle"].document_version_id:
                    new_bundle = context["new_bundle"]
                    old_bundle = context.get("old_bundle")
                    self.registry.register_bundle_contributions(new_bundle, batch_id=batch_id, active=True)
                    self._set_version_state(new_bundle.document_version_id, "ACTIVE", batch_id, "active_switch")
                    if old_bundle:
                        self._set_version_state(old_bundle.document_version_id, "SUPERSEDED", batch_id, "new_version_active")
                    self._remember_bundle(new_bundle)
                elif context.get("rebuild_bundle"):
                    rebuild_bundle = context["rebuild_bundle"]
                    self.registry.register_bundle_contributions(rebuild_bundle, batch_id=batch_id, active=True)
                    self.repository.set_document_active_version(rebuild_bundle.document_id, rebuild_bundle.document_version_id, batch_id)
                    self._remember_bundle(rebuild_bundle)
            return old_active if "old_active" in locals() else None
        if op.operation_kind == "DEACTIVATE_DOCUMENT_VERSION":
            self.registry.deactivate_version(op.target_id, batch_id=batch_id)
            if op.target_id != "NO_ACTIVE_VERSION":
                self._set_version_state(op.target_id, "DELETED" if context.get("delete_bundle") or context.get("delete_document_bundles") else "SUPERSEDED", batch_id, "contributions_deactivated")
            return None
        if op.operation_kind == "CREATE_TOMBSTONE":
            if op.target_kind == "logical_document":
                self.repository.create_tombstone({"tombstone_id": f"tomb:{op.target_id}:{batch_id}", "document_id": op.target_id, "delete_scope": "LOGICAL_DOCUMENT", "reason_code": op.reason, "deleted_by_batch_id": batch_id})
            else:
                bundle = context.get("delete_bundle")
                self.repository.create_tombstone({"tombstone_id": f"tomb:{op.target_id}:{batch_id}", "document_id": bundle.document_id if bundle else context_document_id(context, op, self), "document_version_id": op.target_id, "delete_scope": "DOCUMENT_VERSION", "reason_code": op.reason, "deleted_by_batch_id": batch_id})
            return None
        if op.operation_kind in {"OPEN_ISSUE", "RESOLVE_ISSUE"}:
            return None
        raise ValueError(f"unsupported_operation:{op.operation_kind}")

    def _can_delete(self, op: MutationOperation) -> bool:
        if op.target_kind == "raw_chunk" or op.target_kind == "chunk_vector":
            return self.registry.active_chunk_contribution_count(op.target_id) == 0
        if op.target_kind == "semantic_object" or op.target_kind == "entity_vector":
            return self.registry.active_object_contribution_count(op.target_id) == 0
        if op.target_kind == "semantic_relation" or op.target_kind == "relation_vector":
            return self.registry.active_relation_contribution_count(op.target_id) == 0
        return True

    def _apply_full_projection(self, bundle: LifecycleDocumentBundle) -> None:
        for chunk in bundle.raw_chunks:
            self.adapter.upsert_raw_chunk(chunk)
            self.adapter.upsert_chunk_vector(chunk)
        for obj in bundle.semantic_objects:
            self.adapter.upsert_pfss_node(obj)
            self.adapter.upsert_entity_vector(obj)
        for rel in bundle.semantic_relations:
            self.adapter.upsert_pfss_edge(rel)
            self.adapter.upsert_relation_vector(rel)

    def _remove_extra_projection_for_bundle(self, bundle: LifecycleDocumentBundle) -> None:
        expected_chunks = {stable_chunk_id(chunk) for chunk in bundle.raw_chunks}
        expected_objects = {str(obj["semantic_object_id"]) for obj in bundle.semantic_objects}
        expected_relations = {str(rel["semantic_relation_id"]) for rel in bundle.semantic_relations}
        for rel_id in sorted(set(self.adapter.pfss_edges) - expected_relations):
            if self.registry.active_relation_contribution_count(rel_id) == 0:
                self.adapter.delete_pfss_edge(rel_id)
                self.adapter.delete_relation_vector(rel_id)
        for obj_id in sorted(set(self.adapter.pfss_nodes) - expected_objects):
            if self.registry.active_object_contribution_count(obj_id) == 0:
                self.adapter.delete_pfss_node(obj_id)
                self.adapter.delete_entity_vector(obj_id)
        for chunk_id in sorted(set(self.adapter.raw_chunks) - expected_chunks):
            if self.registry.active_chunk_contribution_count(chunk_id) == 0:
                self.adapter.delete_raw_chunk(chunk_id)
                self.adapter.delete_chunk_vector(chunk_id)

    def _persist_base_bundle(self, bundle: LifecycleDocumentBundle, *, batch_id: str, status: str, skip_existing_semantic: bool = False) -> None:
        objects = bundle.semantic_objects
        relations = bundle.semantic_relations
        if skip_existing_semantic:
            objects = [obj for obj in objects if not self.repository._one("SELECT semantic_object_id FROM semantic_objects WHERE semantic_object_id = ?", (obj["semantic_object_id"],))]
            relations = [rel for rel in relations if not self.repository._one("SELECT semantic_relation_id FROM semantic_relations WHERE semantic_relation_id = ?", (rel["semantic_relation_id"],))]
        sidecar_bundle = SidecarPersistenceBundle(
            batch=IngestionBatchRecord(batch_id=batch_id, trace_id=f"trace:{batch_id}", requested_mode="shadow", semantic_route="DSL_FULL", started_at=_now()),
            document=bundle.document,
            document_version={**bundle.document_version, "status": status},
            raw_chunks=bundle.raw_chunks,
            source_text_units=bundle.source_text_units,
            chunk_text_unit_links=bundle.chunk_text_unit_links,
            semantic_objects=objects,
            semantic_relations=relations,
            issues=bundle.issues,
        )
        self.repository.persist_bundle(sidecar_bundle)

    def _ensure_batch(self, batch_id: str, *, trace_id: str, route: str) -> None:
        if self.repository.get_batch(batch_id):
            return
        self.repository.begin_batch(
            IngestionBatchRecord(
                batch_id=batch_id,
                trace_id=trace_id,
                requested_mode="shadow",
                semantic_route=route,
                policy_version="24C-1-policy",
                ontology_version="24C-1-ontology",
                term_registry_version="24C-1-terms",
                started_at=_now(),
            )
        )

    def _set_version_state(self, document_version_id: str, new_status: str, batch_id: str, reason: str) -> None:
        current = self.repository.get_document_version(document_version_id)
        old_status = current.get("status") if current else None
        self.repository.update_document_version_status(document_version_id, new_status)
        self.repository.record_version_state(document_version_id, old_status, new_status, batch_id, reason)

    def _remember_bundle(self, bundle: LifecycleDocumentBundle) -> None:
        self.registered_bundles[bundle.document_version_id] = bundle
        versions = self.document_versions.setdefault(bundle.document_id, [])
        if bundle.document_version_id not in versions:
            versions.append(bundle.document_version_id)

    def _embedding_counts(self) -> dict[str, int]:
        return {
            "embedding_input_count": self.adapter.embedding.input_count,
            "embedding_reused_count": self.adapter.embedding.reused_count,
            "embedding_recomputed_count": self.adapter.embedding.recomputed_count,
        }


def build_lifecycle_fixture_bundle(version: str, *, document_id: str = "US-SYN-001", previous_version_id: str | None = None) -> LifecycleDocumentBundle:
    now = _now()
    normalized = _fixture_text(version)
    version_id = f"docver:{document_id}:{version}"
    document = {
        "document_id": document_id,
        "source_uri_hash": _hash(f"synthetic://24c1/{document_id}"),
        "source_type": "synthetic",
        "module_code": "BLOCK24C1",
        "logical_name": "Synthetic product design fixture",
        "created_at": now,
        "updated_at": now,
    }
    document_version = {
        "document_version_id": version_id,
        "document_id": document_id,
        "content_hash": _hash(normalized),
        "parser_name": "block24c1_fixture_compiler",
        "parser_version": "24C-1",
        "normalized_text_hash": _hash(normalized),
        "status": "STAGED",
        "previous_version_id": previous_version_id,
        "created_at": now,
    }
    chunks = _fixture_chunks(version, document_id, version_id, now)
    units = _fixture_text_units(version, document_id, version_id, now)
    links = _fixture_links(chunks, units, document_id, version_id)
    objects = _fixture_objects(version, version_id, now)
    relations = _fixture_relations(version, version_id, now)
    return LifecycleDocumentBundle(document=document, document_version=document_version, raw_chunks=chunks, source_text_units=units, chunk_text_unit_links=links, semantic_objects=objects, semantic_relations=relations)


def build_shared_document_bundle(*, document_id: str = "US-SYN-002") -> LifecycleDocumentBundle:
    now = _now()
    version = "v1"
    version_id = f"docver:{document_id}:{version}"
    document = {
        "document_id": document_id,
        "source_uri_hash": _hash(f"synthetic://24c1/{document_id}"),
        "source_type": "synthetic",
        "module_code": "BLOCK24C1",
        "logical_name": "Shared project status fixture",
        "created_at": now,
        "updated_at": now,
    }
    text = "共享文档同样引用 ProjectStatus 作为项目筛选条件"
    document_version = {
        "document_version_id": version_id,
        "document_id": document_id,
        "content_hash": _hash(text),
        "parser_name": "block24c1_fixture_compiler",
        "parser_version": "24C-1",
        "normalized_text_hash": _hash(text),
        "status": "STAGED",
        "previous_version_id": None,
        "created_at": now,
    }
    chunks = [_chunk(document_id, version_id, "C1", 0, text, now)]
    units = [_text_unit(document_id, version_id, "TU1", 0, text, now)]
    links = _fixture_links(chunks, units, document_id, version_id)
    objects = [
        _object("obj:SharedProjectReport", version_id, "ReportSpec", "Shared Project Report", "shared-report", now),
        _object("obj:ProjectStatus", version_id, "FieldSpec", "ProjectStatus", "status-values-open-closed", now),
    ]
    relations = [_relation("rel:SharedProjectReport:HasReportFilter:ProjectStatus", version_id, "obj:SharedProjectReport", "obj:ProjectStatus", "HasReportFilter", "shared-filter", now)]
    return LifecycleDocumentBundle(document=document, document_version=document_version, raw_chunks=chunks, source_text_units=units, chunk_text_unit_links=links, semantic_objects=objects, semantic_relations=relations)


def context_document_id(context: dict[str, Any], op: MutationOperation, service: DocumentLifecycleService) -> str:
    for key in ("new_bundle", "old_bundle", "delete_bundle", "rebuild_bundle"):
        bundle = context.get(key)
        if bundle:
            return bundle.document_id
    bundles = context.get("delete_document_bundles")
    if bundles:
        return bundles[0].document_id
    active = service.repository.get_active_version(op.target_id)
    if active:
        return active["document_id"]
    return service.repository.get_document_version(op.target_id)["document_id"] if service.repository.get_document_version(op.target_id) else op.target_id


def _lookup_payload(op: MutationOperation, context: dict[str, Any]) -> dict[str, Any]:
    for bundle_key in ("new_bundle", "old_bundle", "delete_bundle", "rebuild_bundle"):
        bundle = context.get(bundle_key)
        if not bundle:
            continue
        for chunk in bundle.raw_chunks:
            if stable_chunk_id(chunk) == op.target_id:
                return chunk
        for obj in bundle.semantic_objects:
            if obj["semantic_object_id"] == op.target_id:
                return obj
        for rel in bundle.semantic_relations:
            if rel["semantic_relation_id"] == op.target_id:
                return rel
    raise KeyError(f"payload_not_found:{op.target_id}")


def _fixture_text(version: str) -> str:
    if version == "v1":
        return "项目列表支持按项目状态查询\n项目状态包含 Open 和 Closed"
    if version == "v2":
        return "项目列表支持按项目状态查询\n项目状态包含 Open、Suspended、Closed\nSuspended 状态禁止提交报价"
    if version == "v3":
        return "项目列表支持按项目状态查询\n项目状态包含 Open、Suspended、Closed\nSuspended 状态需要人工复核"
    raise ValueError(f"unknown fixture version: {version}")


def _fixture_chunks(version: str, document_id: str, version_id: str, now: str) -> list[dict[str, Any]]:
    chunks = [_chunk(document_id, version_id, "C1", 0, "项目列表支持按项目状态查询", now)]
    if version == "v1":
        chunks.append(_chunk(document_id, version_id, "C2", 1, "项目状态包含 Open 和 Closed", now))
    elif version == "v2":
        chunks.append(_chunk(document_id, version_id, "C2", 1, "项目状态包含 Open、Suspended、Closed", now))
        chunks.append(_chunk(document_id, version_id, "C3", 2, "Suspended 状态禁止提交报价", now))
    elif version == "v3":
        chunks.append(_chunk(document_id, version_id, "C2", 1, "项目状态包含 Open、Suspended、Closed", now))
        chunks.append(_chunk(document_id, version_id, "C3", 2, "Suspended 状态需要人工复核", now))
    return chunks


def _fixture_text_units(version: str, document_id: str, version_id: str, now: str) -> list[dict[str, Any]]:
    return [_text_unit(document_id, version_id, f"TU{index + 1}", index, chunk["content"], now) for index, chunk in enumerate(_fixture_chunks(version, document_id, version_id, now))]


def _fixture_links(chunks: list[dict[str, Any]], units: list[dict[str, Any]], document_id: str, version_id: str) -> list[dict[str, Any]]:
    del document_id
    rows = []
    for chunk, unit in zip(chunks, units, strict=True):
        rows.append(
            {
                "link_id": f"link:{version_id}:{stable_chunk_id(chunk)}:{unit['text_unit_id']}",
                "document_version_id": version_id,
                "chunk_id": chunk["chunk_id"],
                "text_unit_id": unit["text_unit_id"],
                "overlap_start_offset": chunk["start_offset"],
                "overlap_end_offset": chunk["end_offset"],
                "overlap_char_count": chunk["end_offset"] - chunk["start_offset"],
                "chunk_coverage_ratio": 1.0,
                "text_unit_coverage_ratio": 1.0,
                "link_type": "CONTAINS",
            }
        )
    return rows


def _fixture_objects(version: str, version_id: str, now: str) -> list[dict[str, Any]]:
    objects = [
        _object("obj:InquiryProjectList", version_id, "ReportSpec", "InquiryProjectList", "project-list-query", now),
        _object("obj:ProjectStatus", version_id, "FieldSpec", "ProjectStatus", "status-values-open-suspended-closed" if version in {"v2", "v3"} else "status-values-open-closed", now),
        _object("obj:Open", version_id, "RuleAtom", "Open", "project-status-open", now),
        _object("obj:Closed", version_id, "RuleAtom", "Closed", "project-status-closed", now),
    ]
    if version in {"v2", "v3"}:
        objects.extend(
            [
                _object("obj:Suspended", version_id, "RuleAtom", "Suspended", "project-status-suspended", now),
                _object("obj:QuoteSubmission", version_id, "TaskRule", "QuoteSubmission", "quote-submission", now),
            ]
        )
    return objects


def _fixture_relations(version: str, version_id: str, now: str) -> list[dict[str, Any]]:
    relations = [_relation("rel:InquiryProjectList:HasReportFilter:ProjectStatus", version_id, "obj:InquiryProjectList", "obj:ProjectStatus", "HasReportFilter", "project-list-filter", now)]
    if version == "v2":
        relations.append(_relation("rel:Suspended:BlocksAction:QuoteSubmission", version_id, "obj:Suspended", "obj:QuoteSubmission", "BlocksAction", "suspended-blocks-quote", now))
    return relations


def _chunk(document_id: str, version_id: str, stable: str, order: int, content: str, now: str) -> dict[str, Any]:
    start = order * 100
    stable_id = f"chunk:{document_id}:{stable}"
    content_hash = _hash(content)
    return {
        "chunk_id": f"chunk:{version_id}:{stable}",
        "stable_id": stable_id,
        "document_version_id": version_id,
        "chunk_order": order,
        "start_offset": start,
        "end_offset": start + len(content),
        "token_count": len(content),
        "content": content,
        "content_hash": content_hash,
        "projection_hash": content_hash,
        "source_span": {"start": start, "end": start + len(content)},
        "created_at": now,
    }


def _text_unit(document_id: str, version_id: str, stable: str, order: int, content: str, now: str) -> dict[str, Any]:
    start = order * 100
    text_hash = _hash(content)
    return {
        "text_unit_id": f"tu:{version_id}:{stable}",
        "stable_id": f"tu:{document_id}:{stable}",
        "document_version_id": version_id,
        "source_us_id": document_id,
        "section_type": "requirement",
        "start_offset": start,
        "end_offset": start + len(content),
        "text_hash": text_hash,
        "projection_hash": text_hash,
        "feature_key": "project-status-query",
        "primary_domain": "ProjectInquiry",
        "related_domains": ["ProjectInquiry"],
        "evidence_excerpt": content,
        "content": content,
        "created_at": now,
    }


def _object(object_id: str, version_id: str, object_type: str, name: str, projection_key: str, now: str) -> dict[str, Any]:
    return {
        "semantic_object_id": object_id,
        "stable_id": object_id,
        "document_version_id": version_id,
        "object_type": object_type,
        "canonical_name": name,
        "domain_code": "ProjectInquiry",
        "feature_key": "project-status-query",
        "knowledge_status": "APPROVED",
        "validation_status": "VALID",
        "review_decision": "APPROVED_PFSS",
        "version_group_key": f"vg:{object_id}",
        "idempotency_key": object_id,
        "projection_hash": _hash(f"{object_id}:{projection_key}"),
        "created_at": now,
        "updated_at": now,
    }


def _relation(relation_id: str, version_id: str, src: str, tgt: str, relation_type: str, projection_key: str, now: str) -> dict[str, Any]:
    return {
        "semantic_relation_id": relation_id,
        "stable_id": relation_id,
        "document_version_id": version_id,
        "src_semantic_object_id": src,
        "relation_type": relation_type,
        "tgt_semantic_object_id": tgt,
        "knowledge_status": "APPROVED",
        "validation_status": "VALID",
        "review_decision": "APPROVED_PFSS",
        "idempotency_key": relation_id,
        "projection_hash": _hash(f"{relation_id}:{projection_key}"),
        "created_at": now,
        "updated_at": now,
    }


def _step_id(mutation_id: str, op: MutationOperation) -> str:
    return f"step:{mutation_id}:{op.order:04d}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
