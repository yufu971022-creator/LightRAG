from __future__ import annotations

from lightrag_ext.us_dsl.sidecar_persistence_service import build_sidecar_fixture_bundle, persist_sidecar_bundle
from lightrag_ext.us_dsl.sidecar_readback_validator import (
    document_version_snapshot,
    readback_counts,
    referential_integrity_report,
    rollback_manifest_readback,
    trace_graph_object_to_evidence,
    validate_write_readback_counts,
    version_group_readback,
)
from lightrag_ext.us_dsl.sidecar_registry_types import SidecarPersistenceConfig
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def _repo_with_full():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()
    bundle = build_sidecar_fixture_bundle("DSL_FULL", trace_id="trace-readback", document_id="doc-readback")
    result = persist_sidecar_bundle(repository=repo, route_decision="DSL_FULL", unified_parse_result=bundle, raw_evidence_result=None, semantic_branch_result=None, config=SidecarPersistenceConfig())
    return repo, bundle, result


def test_graph_object_can_trace_to_evidence():
    repo, _, _ = _repo_with_full()

    trace = trace_graph_object_to_evidence(repo, graph_space="PFSS", graph_namespace="pfss_test_graph", graph_object_kind="node", graph_object_id="sem:bank_status")

    assert trace is not None
    assert trace["document"] is not None
    assert trace["evidence"]
    assert trace["text_unit_id"] is not None


def test_document_version_can_list_graph_objects():
    repo, bundle, _ = _repo_with_full()

    snapshot = document_version_snapshot(repo, bundle.document_version["document_version_id"])

    assert len(snapshot["semantic_objects"]) == 2
    assert len(snapshot["semantic_relations"]) == 1
    assert len(snapshot["graph_object_mappings"]) == 3
    assert snapshot["issues"] == []


def test_version_group_readback():
    repo, _, _ = _repo_with_full()

    group = version_group_readback(repo, "vg-bank-status")

    assert group["group"]["version_group_key"] == "vg-bank-status"
    assert len(group["members"]) == 1
    assert group["members"][0]["latest_flag"] == 1


def test_batch_rollback_manifest_readback():
    repo, _, result = _repo_with_full()

    manifest = rollback_manifest_readback(repo, result.batch_id)

    assert len(manifest) == 3
    assert {row["planned_action"] for row in manifest} == {"DELETE_GRAPH_OBJECT"}


def test_referential_integrity_report_passes():
    repo, _, _ = _repo_with_full()

    report = referential_integrity_report(repo)

    assert report["passed"] is True
    assert report["foreign_key_violations"] == []


def test_readback_counts_match_write_counts():
    repo, bundle, result = _repo_with_full()

    counts = readback_counts(repo, bundle.document_version["document_version_id"], result.batch_id)
    validation = validate_write_readback_counts(repo, {"semantic_objects_count": 2, "semantic_relations_count": 1})

    assert counts["semantic_objects"] == 2
    assert counts["semantic_relations"] == 1
    assert counts["graph_object_mappings"] == 3
    assert validation["passed"] is True
