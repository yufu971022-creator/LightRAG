from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.tests.unified_e2e_test_helpers import run


def test_query_requires_trusted_context_pack(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert all(query.trusted_context_pack_created for query in result.queries)


def test_functional_qa_executes_after_context(tmp_path: Path) -> None:
    result = run(tmp_path)
    stages = [event["stage"] for event in result.trace_events]
    assert stages.index("QUERY_CONTEXT_READY") < stages.index("FUNCTIONAL_QA_EXECUTED")


def test_impact_analysis_executes_after_functional_qa(tmp_path: Path) -> None:
    result = run(tmp_path)
    stages = [event["stage"] for event in result.trace_events]
    assert stages.index("FUNCTIONAL_QA_EXECUTED") < stages.index("IMPACT_ANALYSIS_EXECUTED")


def test_version_warning_and_text_only_paths_are_visible(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert any(query.version_warning_passed for query in result.queries)
    assert any(query.text_only_fallback_passed for query in result.queries)
