from __future__ import annotations

import inspect
import sqlite3

import pytest

from lightrag_ext.us_dsl.sidecar_persistence_service import build_sidecar_fixture_bundle, persist_sidecar_bundle
from lightrag_ext.us_dsl.sidecar_registry_types import IngestionBatchRecord, SidecarPersistenceConfig
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def _repo() -> SQLiteSidecarRepository:
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()
    return repo


def _persist(repo: SQLiteSidecarRepository, route: str = "DSL_FULL"):
    bundle = build_sidecar_fixture_bundle(route, trace_id=f"trace-repo-{route.lower()}", document_id=f"doc-repo-{route.lower()}")
    return persist_sidecar_bundle(repository=repo, route_decision=route, unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())


def test_document_and_version_upsert_are_idempotent():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-retry", document_id="doc-retry")

    persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())
    persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())

    assert repo.count_table("documents") == 1
    assert repo.count_table("document_versions") == 1


def test_batch_trace_id_is_unique():
    repo = _repo()
    repo.begin_batch(IngestionBatchRecord(batch_id="batch-a", trace_id="trace-same", requested_mode="shadow", semantic_route="DSL_FULL"))

    with pytest.raises(sqlite3.IntegrityError):
        repo.begin_batch(IngestionBatchRecord(batch_id="batch-b", trace_id="trace-same", requested_mode="shadow", semantic_route="DSL_FULL"))


def test_source_text_unit_references_document_version():
    repo = _repo()
    result = _persist(repo, "DSL_FULL")

    units = repo.list_source_text_units(result.document_version_id)
    assert len(units) == 3
    assert all(unit["document_version_id"] == result.document_version_id for unit in units)


def test_relation_endpoints_require_existing_objects():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-bad-relation", document_id="doc-bad-relation")
    bad_relation = {**bundle.semantic_relations[0], "tgt_semantic_object_id": "missing-object"}
    bad_bundle = type(bundle)(**{**bundle.__dict__, "semantic_relations": [bad_relation]})
    repo.begin_batch(bad_bundle.batch)

    with pytest.raises(sqlite3.IntegrityError):
        repo.persist_bundle(bad_bundle)


def test_graph_mapping_is_unique_per_namespace_object():
    repo = _repo()
    _persist(repo, "DSL_FULL")
    mapping = repo._one("SELECT * FROM graph_object_mappings WHERE graph_object_kind = ? LIMIT 1", ("node",))

    with pytest.raises(sqlite3.IntegrityError):
        repo._execute(
            """
            INSERT INTO graph_object_mappings (mapping_id, batch_id, graph_space, graph_namespace, graph_object_kind, graph_object_id, semantic_object_id, rollback_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("map-duplicate", mapping["batch_id"], mapping["graph_space"], mapping["graph_namespace"], mapping["graph_object_kind"], mapping["graph_object_id"], mapping["semantic_object_id"], "rb-dup", "now"),
        )


def test_issue_idempotency():
    repo = _repo()
    bundle = build_sidecar_fixture_bundle("DSL_PARTIAL", trace_id="trace-issues", document_id="doc-issues")

    persist_sidecar_bundle(repository=repo, route_decision="DSL_PARTIAL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())
    persist_sidecar_bundle(repository=repo, route_decision="DSL_PARTIAL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())

    assert repo.count_table("ingestion_issues") == 2


def test_rollback_manifest_is_queryable():
    repo = _repo()
    result = _persist(repo, "DSL_FULL")

    manifest = repo.get_rollback_manifest(result.batch_id)
    assert len(manifest) == 3
    assert all(row["execution_status"] == "NOT_EXECUTED" for row in manifest)


def test_parameterized_sql_is_used():
    source = inspect.getsource(SQLiteSidecarRepository._execute)

    assert "params" in source
    assert "self._conn.execute(sql, params)" in source
