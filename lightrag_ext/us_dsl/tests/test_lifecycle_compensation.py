from __future__ import annotations

from lightrag_ext.us_dsl.document_lifecycle_service import DocumentLifecycleService, build_lifecycle_fixture_bundle
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def _service():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()

    repo.apply_lifecycle_migration()
    return DocumentLifecycleService(repository=repo)


def _failed(kind: str, *, fail_compensation: bool = False):
    service = _service()
    v1 = build_lifecycle_fixture_bundle("v1")
    v2 = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    service.register_initial_version(v1, batch_id="b1")
    result = service.upsert_new_version(old_bundle=v1, new_bundle=v2, batch_id=f"b-{kind}", fail_after_operation_kind=kind, fail_compensation=fail_compensation)
    return service, v1, v2, result


def test_failure_after_edge_write_compensates_new_projection():
    service, v1, _, result = _failed("UPSERT_PFSS_EDGE")
    assert result.mutation_result.status == "COMPENSATED"
    assert service.adapter.counts()["pfss_edge_count"] == len(v1.semantic_relations)


def test_failure_after_active_switch_restores_old_active_version():
    service, v1, _, result = _failed("ACTIVATE_DOCUMENT_VERSION")
    assert result.mutation_result.status == "COMPENSATED"
    assert service.repository.get_active_version(v1.document_id)["active_document_version_id"] == v1.document_version_id


def test_compensation_runs_in_reverse_order():
    _, _, _, result = _failed("UPSERT_PFSS_EDGE")
    assert result.compensation is not None
    assert result.compensation.reverse_order_passed


def test_compensation_result_matches_preimage():
    service, v1, _, result = _failed("ACTIVATE_DOCUMENT_VERSION")
    assert result.compensation is not None
    assert service.adapter.counts()["raw_chunk_count"] == len(v1.raw_chunks)
    assert service.adapter.counts()["pfss_node_count"] == len(v1.semantic_objects)


def test_compensation_failure_marks_rebuild_required():
    service, _, v2, result = _failed("UPSERT_PFSS_EDGE", fail_compensation=True)
    assert result.mutation_result.status == "FAILED"
    assert service.compensation_failure_marks_rebuild_required
    assert service.repository.get_document_version(v2.document_version_id)["status"] == "REBUILD_REQUIRED"


def test_no_half_applied_mutation_remains():
    service, _, _, _ = _failed("UPSERT_PFSS_EDGE")
    rows = service.repository._all("SELECT COUNT(*) AS count FROM lifecycle_mutations WHERE status = 'APPLYING'")
    assert rows[0]["count"] == 0
