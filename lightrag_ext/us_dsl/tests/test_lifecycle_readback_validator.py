from __future__ import annotations

from lightrag_ext.us_dsl.document_lifecycle_service import DocumentLifecycleService, build_lifecycle_fixture_bundle
from lightrag_ext.us_dsl.lifecycle_readback_validator import validate_cross_store_projection
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def _service_with_v2():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()

    repo.apply_lifecycle_migration()
    service = DocumentLifecycleService(repository=repo)
    v1 = build_lifecycle_fixture_bundle("v1")
    v2 = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    service.register_initial_version(v1, batch_id="b1")
    service.upsert_new_version(old_bundle=v1, new_bundle=v2, batch_id="b2")
    return service, v1, v2


def test_rebuild_restores_missing_raw_projection():
    service, _, v2 = _service_with_v2()
    service.adapter.delete_raw_chunk("chunk:US-SYN-001:C1")
    service.adapter.delete_chunk_vector("chunk:US-SYN-001:C1")
    service.rebuild_document_version(document_version_id=v2.document_version_id, batch_id="b3")
    assert "chunk:US-SYN-001:C1" in service.adapter.raw_chunks
    assert "chunk:US-SYN-001:C1" in service.adapter.chunk_vectors


def test_rebuild_restores_missing_pfss_projection():
    service, _, v2 = _service_with_v2()
    service.adapter.delete_pfss_edge("rel:InquiryProjectList:HasReportFilter:ProjectStatus")
    service.adapter.delete_relation_vector("rel:InquiryProjectList:HasReportFilter:ProjectStatus")
    service.rebuild_document_version(document_version_id=v2.document_version_id, batch_id="b3")
    assert "rel:InquiryProjectList:HasReportFilter:ProjectStatus" in service.adapter.pfss_edges


def test_rebuild_removes_extra_projection():
    service, _, v2 = _service_with_v2()
    service.adapter.upsert_pfss_node({"semantic_object_id": "obj:Extra", "canonical_name": "Extra", "object_type": "FieldSpec"})
    service.adapter.upsert_entity_vector({"semantic_object_id": "obj:Extra", "canonical_name": "Extra", "projection_hash": "extra"})
    service.rebuild_document_version(document_version_id=v2.document_version_id, batch_id="b3")
    assert "obj:Extra" not in service.adapter.pfss_nodes
    assert "obj:Extra" not in service.adapter.entity_vectors


def test_rebuild_uses_registered_bundle_without_llm():
    service, _, v2 = _service_with_v2()
    result = service.rebuild_document_version(document_version_id=v2.document_version_id, batch_id="b3")
    assert result.mutation_result.status == "APPLIED"
    assert service.adapter.real_model_called is False


def test_rebuild_is_idempotent():
    service, _, v2 = _service_with_v2()
    service.rebuild_document_version(document_version_id=v2.document_version_id, batch_id="b3")
    before = service.adapter.counts()
    service.rebuild_document_version(document_version_id=v2.document_version_id, batch_id="b4")
    assert service.adapter.counts() == before


def test_cross_store_projection_matches_sidecar():
    service, _, v2 = _service_with_v2()
    report = validate_cross_store_projection(repository=service.repository, adapter=service.adapter, document_id=v2.document_id, expected_active_version_id=v2.document_version_id)
    assert report.passed


def test_graph_has_no_dangling_edges():
    service, _, _ = _service_with_v2()
    assert service.adapter.dangling_edge_count() == 0


def test_no_duplicate_raw_chunks_or_vectors():
    service, _, _ = _service_with_v2()
    assert len(service.adapter.raw_chunks) == len(set(service.adapter.raw_chunks))
    assert len(service.adapter.chunk_vectors) == len(set(service.adapter.chunk_vectors))


def test_no_issue_objects_written_to_pfss():
    service, _, _ = _service_with_v2()
    assert service.adapter.issue_object_written_to_pfss_count() == 0
