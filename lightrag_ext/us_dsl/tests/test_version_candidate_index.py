from __future__ import annotations

from lightrag_ext.us_dsl.tests.version_retrieval_test_helpers import candidate_index


def test_candidate_index_reads_canonical_version_group() -> None:
    rows = candidate_index().query_by_version_group_key("vg:unique-current")
    assert {item.version_member_id for item in rows} == {"m:uc:v1", "m:uc:v2"}


def test_active_contribution_used_for_current_search() -> None:
    rows = candidate_index().current_search_candidates("vg:deleted")
    assert {item.version_member_id for item in rows} == {"m:del:v2"}


def test_historical_registry_available_for_history_search() -> None:
    rows = candidate_index().history_search_candidates("vg:deleted")
    assert {item.version_member_id for item in rows} == {"m:del:v1", "m:del:v2"}


def test_deleted_projection_not_used_as_current() -> None:
    rows = candidate_index().current_search_candidates("vg:deleted")
    assert all(item.document_version_status != "DELETED" for item in rows)
