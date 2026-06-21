from __future__ import annotations

from lightrag_ext.us_dsl.document_lifecycle_service import DocumentLifecycleService, build_lifecycle_fixture_bundle, build_shared_document_bundle
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def _service():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()

    repo.apply_lifecycle_migration()
    return DocumentLifecycleService(repository=repo)


def _v1_v2_service():
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    v2 = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    service.register_initial_version(v1, batch_id="b1")
    result = service.upsert_new_version(old_bundle=v1, new_bundle=v2, batch_id="b2")
    return service, v1, v2, result


def test_upsert_new_version_changes_active_pointer():
    service, _, v2, result = _v1_v2_service()
    assert result.mutation_result.status == "APPLIED"
    assert service.repository.get_active_version(v2.document_id)["active_document_version_id"] == v2.document_version_id


def test_old_version_becomes_superseded():
    service, v1, _, _ = _v1_v2_service()
    assert service.repository.get_document_version(v1.document_version_id)["status"] == "SUPERSEDED"


def test_new_version_becomes_active():
    service, _, v2, _ = _v1_v2_service()
    assert service.repository.get_document_version(v2.document_version_id)["status"] == "ACTIVE"


def test_unchanged_chunks_are_not_reembedded():
    _, _, _, result = _v1_v2_service()
    assert result.embedding_after["embedding_recomputed_count"] - result.embedding_before["embedding_recomputed_count"] == 6


def test_only_changed_semantic_vectors_are_recomputed():
    service, _, _, result = _v1_v2_service()
    delta = result.embedding_after["embedding_recomputed_count"] - result.embedding_before["embedding_recomputed_count"]
    assert delta == 6
    assert service.adapter.embedding.recomputed_count == result.embedding_after["embedding_recomputed_count"]


def test_old_historical_registry_is_retained():
    service, v1, _, _ = _v1_v2_service()
    assert service.repository.get_document_version(v1.document_version_id) is not None
    assert service.repository.list_contributions_for_version(v1.document_version_id)["raw_chunks"]


def test_document_version_update_does_not_create_business_supersedes():
    service, _, _, _ = _v1_v2_service()
    rows = service.repository._all("SELECT COUNT(*) AS count FROM version_members WHERE supersedes_member_id IS NOT NULL")
    assert rows[0]["count"] == 0


def test_delete_active_version_does_not_restore_previous_by_default():
    service, v1, v2, _ = _v1_v2_service()
    service.delete_document_version(bundle=v2, batch_id="b3")
    assert service.repository.get_active_version(v1.document_id)["active_document_version_id"] is None


def test_delete_version_removes_only_zero_contribution_projection():
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    shared = build_shared_document_bundle()
    service.register_initial_version(v1, batch_id="b1")
    service.register_initial_version(shared, batch_id="b2")
    service.delete_document_version(bundle=v1, batch_id="b3")
    assert "obj:ProjectStatus" in service.adapter.pfss_nodes
    assert "obj:InquiryProjectList" not in service.adapter.pfss_nodes


def test_delete_logical_document_keeps_shared_semantic_objects():
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    shared = build_shared_document_bundle()
    service.register_initial_version(v1, batch_id="b1")
    service.register_initial_version(shared, batch_id="b2")
    service.delete_logical_document(document_id=v1.document_id, batch_id="b3")
    assert "obj:ProjectStatus" in service.adapter.pfss_nodes


def test_delete_creates_tombstone():
    service, v1, v2, _ = _v1_v2_service()
    service.delete_document_version(bundle=v2, batch_id="b3")
    assert service.repository.list_tombstones(v1.document_id)


def test_delete_preserves_audit_metadata():
    service, v1, v2, _ = _v1_v2_service()
    service.delete_document_version(bundle=v2, batch_id="b3")
    assert service.repository.get_document(v1.document_id) is not None
    assert service.repository.get_document_version(v1.document_version_id) is not None


def test_delete_produces_no_dangling_edges():
    service, _, v2, _ = _v1_v2_service()
    service.delete_document_version(bundle=v2, batch_id="b3")
    assert service.adapter.dangling_edge_count() == 0
