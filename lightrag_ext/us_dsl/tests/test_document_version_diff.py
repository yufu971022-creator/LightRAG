from __future__ import annotations

from lightrag_ext.us_dsl.document_lifecycle_service import build_lifecycle_fixture_bundle
from lightrag_ext.us_dsl.document_version_diff import build_document_version_diff


def test_same_bundle_produces_empty_diff():
    v1 = build_lifecycle_fixture_bundle("v1")
    diff = build_document_version_diff(v1, v1)
    assert diff.is_empty


def test_content_change_produces_new_document_version():
    v1 = build_lifecycle_fixture_bundle("v1")
    v2 = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    diff = build_document_version_diff(v1, v2)
    assert diff.content_changed is True
    assert diff.old_document_version_id != diff.new_document_version_id


def test_added_updated_removed_chunks_are_detected():
    v1 = build_lifecycle_fixture_bundle("v1")
    v2 = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    diff = build_document_version_diff(v1, v2)
    assert [item.stable_id for item in diff.unchanged_chunks] == ["chunk:US-SYN-001:C1"]
    assert [item.stable_id for item in diff.updated_chunks] == ["chunk:US-SYN-001:C2"]
    assert [item.stable_id for item in diff.added_chunks] == ["chunk:US-SYN-001:C3"]
    assert diff.removed_chunks == []


def test_semantic_object_diff_uses_stable_id_and_projection_hash():
    v1 = build_lifecycle_fixture_bundle("v1")
    v2 = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    diff = build_document_version_diff(v1, v2)
    assert "obj:ProjectStatus" in {item.stable_id for item in diff.updated_semantic_objects}
    assert "obj:Suspended" in {item.stable_id for item in diff.added_semantic_objects}


def test_relation_diff_is_deterministic():
    v1 = build_lifecycle_fixture_bundle("v1")
    v2 = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    diff_a = build_document_version_diff(v1, v2)
    shuffled = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    shuffled = type(shuffled)(
        document=shuffled.document,
        document_version=shuffled.document_version,
        raw_chunks=list(reversed(shuffled.raw_chunks)),
        source_text_units=list(reversed(shuffled.source_text_units)),
        chunk_text_unit_links=shuffled.chunk_text_unit_links,
        semantic_objects=list(reversed(shuffled.semantic_objects)),
        semantic_relations=list(reversed(shuffled.semantic_relations)),
        issues=shuffled.issues,
    )
    diff_b = build_document_version_diff(v1, shuffled)
    assert [item.stable_id for item in diff_a.added_semantic_relations] == [item.stable_id for item in diff_b.added_semantic_relations]


def test_order_only_change_is_not_semantic_update():
    v2 = build_lifecycle_fixture_bundle("v2")
    shuffled = type(v2)(
        document=v2.document,
        document_version=v2.document_version,
        raw_chunks=list(reversed(v2.raw_chunks)),
        source_text_units=list(reversed(v2.source_text_units)),
        chunk_text_unit_links=v2.chunk_text_unit_links,
        semantic_objects=list(reversed(v2.semantic_objects)),
        semantic_relations=list(reversed(v2.semantic_relations)),
        issues=v2.issues,
    )
    diff = build_document_version_diff(v2, shuffled)
    assert diff.is_empty
