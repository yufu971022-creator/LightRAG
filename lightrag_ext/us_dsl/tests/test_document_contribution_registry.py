from __future__ import annotations

from lightrag_ext.us_dsl.document_lifecycle_service import DocumentLifecycleService, build_lifecycle_fixture_bundle, build_shared_document_bundle
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def _service():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()

    repo.apply_lifecycle_migration()
    return DocumentLifecycleService(repository=repo)


def test_shared_object_has_multiple_active_contributions():
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    shared = build_shared_document_bundle()
    service.register_initial_version(v1, batch_id="b1")
    service.register_initial_version(shared, batch_id="b2")
    assert service.registry.active_object_contribution_count("obj:ProjectStatus") == 2


def test_delete_one_contribution_keeps_shared_object():
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    shared = build_shared_document_bundle()
    service.register_initial_version(v1, batch_id="b1")
    service.register_initial_version(shared, batch_id="b2")
    service.delete_logical_document(document_id=v1.document_id, batch_id="b3")
    assert "obj:ProjectStatus" in service.adapter.pfss_nodes
    assert service.registry.active_object_contribution_count("obj:ProjectStatus") == 1


def test_zero_contribution_allows_projection_delete():
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    service.register_initial_version(v1, batch_id="b1")
    service.delete_document_version(bundle=v1, batch_id="b2")
    assert "obj:InquiryProjectList" not in service.adapter.pfss_nodes


def test_relation_deleted_before_orphan_node():
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    service.register_initial_version(v1, batch_id="b1")
    plan = service.delete_document_version(bundle=v1, batch_id="b2").plan
    relation_order = min(op.order for op in plan.operations if op.operation_kind == "DELETE_PFSS_EDGE")
    node_order = min(op.order for op in plan.operations if op.operation_kind == "DELETE_PFSS_NODE")
    assert relation_order < node_order
    assert service.adapter.dangling_edge_count() == 0


def test_contribution_counts_are_idempotent():
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    service.register_initial_version(v1, batch_id="b1")
    service.registry.register_bundle_contributions(v1, batch_id="b1", active=True)
    assert service.registry.active_object_contribution_count("obj:ProjectStatus") == 1
