from __future__ import annotations

import pytest

from lightrag_ext.us_dsl.sidecar_persistence_service import build_sidecar_fixture_bundle, persist_sidecar_bundle
from lightrag_ext.us_dsl.sidecar_registry_types import SidecarPersistenceConfig
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def _repo() -> SQLiteSidecarRepository:
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()
    return repo


def _persist(repo: SQLiteSidecarRepository, bundle):
    return persist_sidecar_bundle(repository=repo, route_decision=bundle.batch.semantic_route, unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())


def test_dsl_full_bundle_persists_all_expected_records():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-full", document_id="doc-full")
    result = _persist(repo, bundle)
    counts = result.record_counts

    assert result.status == "COMPLETED"
    assert counts["raw_chunks_count"] == 2
    assert counts["source_text_units_count"] == 3
    assert counts["semantic_objects_count"] == 2
    assert counts["semantic_relations_count"] == 1
    assert counts["evidence_mappings_count"] == 3
    assert counts["rollback_records_count"] == 3


def test_dsl_partial_bundle_persists_safe_objects_and_issues():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_PARTIAL", trace_id="trace-partial", document_id="doc-partial")
    result = _persist(repo, bundle)

    assert result.status == "COMPLETED"
    assert result.record_counts["semantic_objects_count"] == 2
    assert result.record_counts["semantic_relations_count"] == 1
    assert result.record_counts["ingestion_issues_count"] == 2


def test_raw_only_persists_no_semantic_objects():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("RAW_ONLY", trace_id="trace-raw", document_id="doc-raw")
    result = _persist(repo, bundle)

    assert result.status == "COMPLETED"
    assert result.record_counts["raw_chunks_count"] == 2
    assert result.record_counts["semantic_objects_count"] == 0
    assert result.record_counts["semantic_relations_count"] == 0
    assert result.record_counts["graph_object_mappings_count"] == 0


def test_parse_failed_persists_only_failure_registry():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("PARSE_FAILED", trace_id="trace-parse-failed", document_id="doc-parse-failed")
    result = _persist(repo, bundle)

    assert result.status == "FAILED"
    assert repo.get_batch(result.batch_id)["status"] == "FAILED"
    assert result.record_counts["documents_count"] == 1
    assert result.record_counts["document_versions_count"] == 1
    assert result.record_counts["raw_chunks_count"] == 0
    assert result.record_counts["semantic_objects_count"] == 0


def test_same_payload_retry_is_idempotent():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-idem", document_id="doc-idem")
    first = _persist(repo, bundle)
    second = _persist(repo, bundle)

    assert first.record_counts == second.record_counts


def test_new_batch_same_version_does_not_duplicate_business_rows():
    repo = _repo()
    first = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-new-batch-a", document_id="doc-new-batch")
    second = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-new-batch-b", document_id="doc-new-batch")
    _persist(repo, first)
    before = repo.record_counts()
    _persist(repo, second)
    after = repo.record_counts()

    for key in ["documents_count", "document_versions_count", "semantic_objects_count", "semantic_relations_count", "evidence_mappings_count"]:
        assert after[key] == before[key]
    assert after["ingestion_batches_count"] == before["ingestion_batches_count"] + 1


def test_failure_rolls_back_all_business_rows():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-failure", document_id="doc-failure", fail_after_semantic_relations=True)
    result = _persist(repo, bundle)

    assert result.status == "FAILED"
    assert repo.get_document(bundle.document["document_id"]) is None
    assert repo.count_table("semantic_relations") == 0
    assert repo.count_table("graph_object_mappings") == 0
    assert repo.count_table("evidence_mappings") == 0


def test_failed_batch_status_is_persisted():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-failed-batch", document_id="doc-failed-batch", fail_after_semantic_relations=True)
    result = _persist(repo, bundle)

    assert repo.get_batch(result.batch_id)["status"] == "FAILED"
    assert repo.get_batch(result.batch_id)["error_code"] == "RuntimeError"


def test_trace_document_version_consistency_is_required():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-bad-consistency", document_id="doc-bad-consistency")
    bad_batch = type(bundle.batch)(**{**bundle.batch.__dict__, "batch_id": "batch-not-derived-from-trace"})
    bad_bundle = type(bundle)(**{**bundle.__dict__, "batch": bad_batch})

    with pytest.raises(ValueError):
        _persist(repo, bad_bundle)
