from __future__ import annotations

from lightrag_ext.us_dsl.document_lifecycle_service import build_lifecycle_fixture_bundle
from lightrag_ext.us_dsl.document_version_diff import build_document_version_diff
from lightrag_ext.us_dsl.multistore_mutation_plan import build_upsert_new_version_plan


def _plan():
    v1 = build_lifecycle_fixture_bundle("v1")
    v2 = build_lifecycle_fixture_bundle("v2", previous_version_id=v1.document_version_id)
    return build_upsert_new_version_plan(build_document_version_diff(v1, v2))


def test_new_version_plan_writes_before_deletes():
    plan = _plan()
    first_delete = min((op.order for op in plan.operations if op.operation_kind.startswith("DELETE_")), default=999)
    last_upsert = max(op.order for op in plan.operations if op.operation_kind.startswith("UPSERT_"))
    assert last_upsert < first_delete


def test_plan_has_compensation_for_each_external_write():
    plan = _plan()
    external = plan.external_write_operations
    assert external
    assert all(op.compensation_operation for op in external)


def test_plan_hash_is_deterministic():
    assert _plan().plan_hash == _plan().plan_hash


def test_unchanged_items_generate_no_mutation():
    v1 = build_lifecycle_fixture_bundle("v1")
    plan = build_upsert_new_version_plan(build_document_version_diff(v1, v1))
    assert not [op for op in plan.operations if op.operation_kind.startswith("UPSERT_") or op.operation_kind.startswith("DELETE_")]


def test_active_version_switch_occurs_after_new_projection_validation():
    plan = _plan()
    validate_order = next(op.order for op in plan.operations if op.operation_kind == "VALIDATE_NEW_PROJECTION")
    switch_order = next(op.order for op in plan.operations if op.operation_kind == "ACTIVATE_DOCUMENT_VERSION")
    assert validate_order < switch_order
