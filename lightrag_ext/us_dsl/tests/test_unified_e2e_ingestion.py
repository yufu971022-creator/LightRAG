from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.tests.unified_e2e_test_helpers import run


def test_single_parse_per_document(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert all(doc.parse_count == 1 for doc in result.documents)


def test_raw_evidence_always_before_semantic_branch(tmp_path: Path) -> None:
    result = run(tmp_path)
    stages = [event["stage"] for event in result.trace_events]
    assert stages.index("RAW_EVIDENCE_INDEXED") < stages.index("DSL_COMPILED")


def test_route_counts_cover_all_branches(tmp_path: Path) -> None:
    result = run(tmp_path)
    routes = {doc.route for doc in result.documents}
    assert routes == {"DSL_FULL", "DSL_PARTIAL", "RAW_ONLY", "PARSE_FAILED"}


def test_term_and_type_precede_identity(tmp_path: Path) -> None:
    result = run(tmp_path)
    semantic_docs = [doc for doc in result.documents if doc.dsl_compiled]
    assert all(doc.term_normalized_before_identity and doc.entity_type_resolved_before_identity for doc in semantic_docs)


def test_pfss_issue_sidecar_are_isolated_by_route(tmp_path: Path) -> None:
    result = run(tmp_path)
    full = next(doc for doc in result.documents if doc.route == "DSL_FULL")
    partial = next(doc for doc in result.documents if doc.route == "DSL_PARTIAL")
    raw = next(doc for doc in result.documents if doc.route == "RAW_ONLY")
    assert full.pfss_written and full.sidecar_persisted
    assert partial.issue_indexed and partial.sidecar_persisted
    assert not raw.pfss_written and not raw.sidecar_persisted
