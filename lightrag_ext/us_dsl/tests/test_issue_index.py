from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.issue_index import IssueIndex, make_issue_record


def _record(issue_type: str = "MISSING_EVIDENCE"):
    return make_issue_record(
        trace_id="trace-issue",
        document_id="doc-issue",
        document_version_id="docver-issue",
        semantic_object_id="issue:missing_evidence",
        object_kind="MissingEvidence",
        issue_type=issue_type,
        reason_code="missing_source",
        evidence_text="Evidence line is missing.",
        source_us_id="US-1",
        text_unit_id="tu-1",
        source_span={"start": 0, "end": 10},
        text_hash="hash-1",
        domain_code="MasterData",
        feature_key="feature-1",
    )


def test_issue_records_are_idempotent(tmp_path: Path):
    index = IssueIndex(tmp_path / "issues.json")
    record = _record()

    index.upsert_many([record])
    index.upsert_many([record])

    assert len(index.all_records()) == 1


def test_issue_records_keep_evidence(tmp_path: Path):
    index = IssueIndex(tmp_path / "issues.json")
    record = _record()
    index.upsert_many([record])

    saved = index.all_records()[0]
    assert saved.evidence_text == "Evidence line is missing."
    assert saved.source_span == {"start": 0, "end": 10}
    assert saved.text_hash == "hash-1"


def test_issue_records_are_not_confirmed(tmp_path: Path):
    index = IssueIndex(tmp_path / "issues.json")
    index.upsert_many([_record()])

    assert index.all_records()[0].confirmed is False
    assert index.summary()["confirmed_count"] == 0


def test_issue_index_is_queryable_by_document_and_type(tmp_path: Path):
    index = IssueIndex(tmp_path / "issues.json")
    index.upsert_many([_record("MISSING_EVIDENCE"), _record("VERSION_REVIEW_REQUIRED")])

    assert len(index.query_by_document("doc-issue")) == 2
    assert len(index.query_by_type("MISSING_EVIDENCE")) == 1
    assert len(index.query_by_source_us("US-1")) == 2
    assert len(index.query_by_semantic_object("issue:missing_evidence")) == 2
