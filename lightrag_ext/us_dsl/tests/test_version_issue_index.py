from __future__ import annotations

from lightrag_ext.us_dsl.tests.version_retrieval_test_helpers import issue_index


def test_version_issue_index_is_queryable() -> None:
    rows = issue_index().query_by_version_group_key("vg:issue")
    assert len(rows) == 1
    assert rows[0].issue_type == "VERSION_REVIEW_REQUIRED"


def test_issue_index_does_not_create_pfss_fact() -> None:
    assert issue_index().snapshot()["pfss_fact_count"] == 0


def test_version_issue_idempotency() -> None:
    index = issue_index()
    rows = index.all_issues()
    index.upsert_many(rows)
    assert index.snapshot()["issue_record_count"] == len(rows)
