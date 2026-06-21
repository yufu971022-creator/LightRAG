from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from lightrag_ext.us_dsl.e2e_graph_pipeline import (
    E2EGraphPipelineConfig,
    run_e2e_graph_pipeline,
    serialize_e2e_graph_pipeline_report,
)
from lightrag_ext.us_dsl.e2e_graph_pipeline_report import E2EGraphPipelineReport


def test_e2e_pipeline_disabled_skips():
    report = run_e2e_graph_pipeline(config=E2EGraphPipelineConfig(enabled=False))

    assert report.skipped is True
    assert report.graph_write_attempted is False
    assert report.graph_write_succeeded is False


def test_e2e_pipeline_runs_offline_if_enabled():
    report = _enabled_report()

    assert report.enabled is True
    assert report.skipped is False
    assert report.namespace == "dsl_test_e2e_graph"
    assert report.graph_write_attempted is True
    assert report.graph_write_succeeded is True
    assert report.neo4j_connected is False
    assert report.cleanup_passed is True
    assert report.rollback_passed is True


def test_e2e_pipeline_generates_eval_summaries():
    report = _enabled_report()

    assert report.retrieval_eval_summary.get("query_count", 0) > 0
    assert report.business_qa_eval_summary.get("case_count", 0) > 0
    assert report.us_generation_eval_summary.get("case_count", 0) > 0
    assert report.impact_analysis_eval_summary.get("case_count", 0) > 0


def test_e2e_pipeline_issue_summary():
    report = _enabled_report()

    assert report.issue_summary.graph_write_failure_count == 0
    assert report.issue_summary.forbidden_relation_count == 0
    assert report.issue_summary.dangling_relationship_count == 0
    assert report.issue_summary.version_review_required_count < 14


def test_e2e_pipeline_after_version_policy_tuning():
    report = _enabled_report()

    assert report.version_review_required_before > report.version_review_required_after
    assert report.version_review_required_after < 14
    assert report.version_review_required_reduction > 0
    assert report.version_safe_for_test_count > 0
    assert report.unsafe_supersedes_blocked_count == 0
    assert report.retrieval_eval_summary["degraded_count"] == 0
    assert report.business_qa_eval_summary["degraded_count"] == 0
    assert report.us_generation_eval_summary["degraded_count"] == 0
    assert report.impact_analysis_eval_summary["degraded_count"] == 0
    assert report.issue_summary.unsupported_claim_count == 0
    assert report.issue_summary.invalid_citation_count == 0


def test_e2e_pipeline_optimization_backlog():
    report = _enabled_report()

    assert report.optimization_backlog
    assert all(item.issue_type for item in report.optimization_backlog)


def test_e2e_pipeline_no_production_write():
    report = _enabled_report()

    assert report.production_write is False
    assert report.formal_graph_written is False
    assert report.test_only is True


def test_e2e_pipeline_no_core_modification():
    repo = Path(__file__).resolve().parents[3]
    e2e_source = (repo / "lightrag_ext" / "us_dsl" / "e2e_graph_pipeline.py").read_text(
        encoding="utf-8"
    )
    policy_source = (repo / "lightrag_ext" / "us_dsl" / "policy_auto_approval.py").read_text(
        encoding="utf-8"
    )

    for forbidden in (
        "lightrag/lightrag.py",
        "lightrag/operate.py",
        "merge_nodes_and_edges",
        "_merge_nodes_then_upsert",
    ):
        assert forbidden not in e2e_source
        assert forbidden not in policy_source


def test_report_serializable():
    report = _enabled_report()

    payload = serialize_e2e_graph_pipeline_report(report)
    assert isinstance(report, E2EGraphPipelineReport)
    json.dumps(payload)


@lru_cache(maxsize=1)
def _enabled_report() -> E2EGraphPipelineReport:
    return run_e2e_graph_pipeline(
        config=E2EGraphPipelineConfig(
            enabled=True,
            namespace="dsl_test_e2e_graph",
            max_chunks=15,
            max_entities=30,
            max_relationships=20,
        )
    )
