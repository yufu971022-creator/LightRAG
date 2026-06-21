from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.graph_space_policy import pfss_descriptor
from lightrag_ext.us_dsl.pfss_graph_writer import SOURCE_REFERENCE_STRATEGY, snapshot_pfss_graph, write_pfss_graph
from lightrag_ext.us_dsl.semantic_branch_types import PfssPayload, SemanticObject, SemanticRelationship


def _entity(object_id: str = "pfss:bank_status", object_type: str = "DomainObject", source_id: str = "chunk-1") -> SemanticObject:
    return SemanticObject(
        object_id=object_id,
        label=object_id.split(":")[-1],
        object_type=object_type,
        disposition="APPROVED_PFSS",
        source_id=source_id,
        evidence_text="evidence",
    )


def _relationship(rel_type: str = "HasField", source_id: str = "chunk-1") -> SemanticRelationship:
    return SemanticRelationship(
        relationship_id=f"pfss:rel:{rel_type}",
        src_id="pfss:bank_status",
        tgt_id="pfss:query_condition",
        relationship_type=rel_type,
        disposition="APPROVED_PFSS",
        source_id=source_id,
        evidence_text="evidence",
    )


def _payload(route: str = "DSL_FULL") -> PfssPayload:
    return PfssPayload(
        document_id="doc-pfss",
        document_version_id="docver-pfss",
        semantic_route=route,
        source_chunk_ids=["chunk-1"],
        safe_entities=[_entity("pfss:bank_status"), _entity("pfss:query_condition", "FieldSpec")],
        safe_relationships=[_relationship()],
    )


def test_dsl_full_writes_safe_pfss_objects(tmp_path: Path):
    result = write_pfss_graph(payload=_payload("DSL_FULL"), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)

    assert result.pfss_write_executed is True
    assert result.node_count == 2
    assert result.edge_count == 1


def test_dsl_partial_writes_only_safe_subset(tmp_path: Path):
    payload = _payload("DSL_PARTIAL")
    blocked = SemanticObject("issue:missing", "Missing Evidence", "MissingEvidence", "BLOCKED_ISSUE", "chunk-1")
    payload = PfssPayload(**{**payload.__dict__, "blocked_objects": [blocked]})

    result = write_pfss_graph(payload=payload, descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)
    snapshot = snapshot_pfss_graph(descriptor=pfss_descriptor(), artifact_root=str(tmp_path))

    assert result.pfss_write_executed is True
    assert "issue:missing" not in snapshot["node_ids"]
    assert snapshot["node_count"] == 2


def test_version_review_object_is_not_written_to_pfss(tmp_path: Path):
    assert _blocked_object_not_written(tmp_path, "VersionReviewRequired")


def test_missing_evidence_object_is_not_written_to_pfss(tmp_path: Path):
    assert _blocked_object_not_written(tmp_path, "MissingEvidence")


def test_invalid_type_is_not_written_to_pfss(tmp_path: Path):
    payload = PfssPayload(**{**_payload().__dict__, "safe_entities": [_entity("pfss:invalid", "InvalidType")]})

    result = write_pfss_graph(payload=payload, descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)

    assert result.pfss_write_executed is False
    assert any("invalid_pfss_type" in issue for issue in result.issues)


def test_forbidden_relation_is_not_written_to_pfss(tmp_path: Path):
    payload = PfssPayload(**{**_payload().__dict__, "safe_relationships": [_relationship("ReviewRequired")], "forbidden_relation_count": 1})

    result = write_pfss_graph(payload=payload, descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)

    assert result.pfss_write_executed is False
    assert "forbidden_relation_count_nonzero" in result.issues


def test_endpoint_closure_is_required(tmp_path: Path):
    relation = SemanticRelationship("pfss:bad_rel", "pfss:missing", "pfss:query_condition", "HasField", "APPROVED_PFSS", "chunk-1")
    payload = PfssPayload(**{**_payload().__dict__, "safe_relationships": [relation], "endpoint_closure_passed": False, "dangling_relationship_count": 1})

    result = write_pfss_graph(payload=payload, descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)

    assert result.pfss_write_executed is False
    assert "endpoint_closure_failed" in result.issues


def test_sidecar_alignment_is_required(tmp_path: Path):
    payload = PfssPayload(**{**_payload().__dict__, "safe_entities": [_entity(source_id="missing-chunk")], "sidecar_alignment_passed": False})

    result = write_pfss_graph(payload=payload, descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)

    assert result.pfss_write_executed is False
    assert "sidecar_alignment_failed" in result.issues


def test_pfss_writer_does_not_call_extract_entities(tmp_path: Path):
    result = write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)

    assert result.status == "WRITTEN"
    assert not hasattr(result, "extract_entities_called")


def test_pfss_writer_does_not_call_llm(tmp_path: Path):
    result = write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)

    assert result.status == "WRITTEN"
    assert not hasattr(result, "llm_called")


def test_pfss_writer_does_not_duplicate_raw_chunks(tmp_path: Path):
    result = write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=7, raw_chunk_vector_count_before=7)

    assert result.source_reference_report.raw_chunk_count_after == 7
    assert result.source_reference_report.raw_chunk_vector_count_after == 7
    assert result.source_reference_report.duplicate_raw_chunk_count == 0


def test_pfss_source_reference_strategy_is_reported(tmp_path: Path):
    result = write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)

    assert result.source_reference_report.strategy == SOURCE_REFERENCE_STRATEGY
    assert result.source_reference_report.strategy == "EXTERNAL_SIDECAR_REFERENCE"


def _blocked_object_not_written(tmp_path: Path, object_type: str) -> bool:
    payload = _payload("DSL_PARTIAL")
    blocked = SemanticObject(f"issue:{object_type}", object_type, object_type, "BLOCKED_ISSUE", "chunk-1")
    payload = PfssPayload(**{**payload.__dict__, "blocked_objects": [blocked]})
    write_pfss_graph(payload=payload, descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)
    snapshot = snapshot_pfss_graph(descriptor=pfss_descriptor(), artifact_root=str(tmp_path))
    return blocked.object_id not in snapshot["node_ids"]


def test_sidecar_alignment_for_pfss_objects(tmp_path: Path):
    write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)
    snapshot = snapshot_pfss_graph(descriptor=pfss_descriptor(), artifact_root=str(tmp_path))

    assert snapshot["sidecar_alignment_passed"] is True
    assert snapshot["sidecar_count"] == snapshot["node_count"] + snapshot["edge_count"]


def test_pfss_relationship_endpoint_closure(tmp_path: Path):
    write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)
    snapshot = snapshot_pfss_graph(descriptor=pfss_descriptor(), artifact_root=str(tmp_path))

    assert snapshot["endpoint_closure_passed"] is True


def test_pfss_contains_no_forbidden_relations(tmp_path: Path):
    write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)
    snapshot = snapshot_pfss_graph(descriptor=pfss_descriptor(), artifact_root=str(tmp_path))

    assert snapshot["forbidden_relation_count"] == 0


def test_pfss_has_no_duplicate_semantic_objects(tmp_path: Path):
    write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)
    write_pfss_graph(payload=_payload(), descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)
    snapshot = snapshot_pfss_graph(descriptor=pfss_descriptor(), artifact_root=str(tmp_path))

    assert snapshot["duplicate_semantic_object_count"] == 0


def test_issue_objects_are_not_written_to_pfss(tmp_path: Path):
    payload = _payload("DSL_PARTIAL")
    blocked = SemanticObject("issue:version_review_required", "VersionReviewRequired", "VersionReviewRequired", "BLOCKED_ISSUE", "chunk-1")
    payload = PfssPayload(**{**payload.__dict__, "blocked_objects": [blocked]})
    write_pfss_graph(payload=payload, descriptor=pfss_descriptor(), artifact_root=str(tmp_path), raw_chunk_count_before=1, raw_chunk_vector_count_before=1)
    snapshot = snapshot_pfss_graph(descriptor=pfss_descriptor(), artifact_root=str(tmp_path))

    assert snapshot["issue_object_written_to_pfss_count"] == 0
    assert blocked.object_id not in snapshot["node_ids"]
