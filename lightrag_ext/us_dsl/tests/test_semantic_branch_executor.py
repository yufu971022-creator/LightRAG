from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lightrag_ext.us_dsl.raw_evidence_chain import RawEvidenceRouteContract, build_fixture_requests, run_raw_evidence_chain
from lightrag_ext.us_dsl.raw_evidence_storage_adapter import RawEvidenceIndexConfig
from lightrag_ext.us_dsl.semantic_branch_executor import execute_fixture_suite, execute_semantic_branch
from lightrag_ext.us_dsl.semantic_branch_types import SemanticBranchExecutionConfig


def _config(tmp_path: Path) -> SemanticBranchExecutionConfig:
    return SemanticBranchExecutionConfig(artifact_root=str(tmp_path))


async def _raw_item(index: int, tmp_path: Path):
    raw_run = await run_raw_evidence_chain(
        requests=[build_fixture_requests()[index]],
        config=RawEvidenceIndexConfig(execution_mode="ISOLATED_WRITE", artifact_root=str(tmp_path), workspace=f"raw-{index}"),
    )
    return raw_run.results[0]


def test_dsl_full_executes_pfss_branch(tmp_path: Path):
    raw_item = asyncio.run(_raw_item(0, tmp_path))
    result = execute_semantic_branch(route_decision=raw_item.route_plan, unified_parse_result=raw_item.parse_result, raw_evidence_result=raw_item.index_result, config=_config(tmp_path))

    assert result.semantic_route == "DSL_FULL"
    assert result.pfss_write_executed is True
    assert result.safe_entity_count == 2
    assert result.issue_index_write_executed is False


def test_dsl_partial_executes_pfss_and_issue_branches(tmp_path: Path):
    raw_item = asyncio.run(_raw_item(1, tmp_path))
    result = execute_semantic_branch(route_decision=raw_item.route_plan, unified_parse_result=raw_item.parse_result, raw_evidence_result=raw_item.index_result, config=_config(tmp_path))

    assert result.semantic_route == "DSL_PARTIAL"
    assert result.pfss_write_executed is True
    assert result.issue_index_write_executed is True
    assert result.issue_record_count == 2


def test_raw_only_does_not_write_pfss(tmp_path: Path):
    raw_item = asyncio.run(_raw_item(2, tmp_path))
    result = execute_semantic_branch(route_decision=raw_item.route_plan, unified_parse_result=raw_item.parse_result, raw_evidence_result=raw_item.index_result, config=_config(tmp_path))

    assert result.semantic_route == "RAW_ONLY"
    assert result.pfss_write_executed is False
    assert result.generic_write_executed is False


def test_parse_failed_does_not_write_any_semantic_space(tmp_path: Path):
    raw_item = asyncio.run(_raw_item(3, tmp_path))
    result = execute_semantic_branch(route_decision=RawEvidenceRouteContract(selected_plan_route="PARSE_FAILED"), unified_parse_result=raw_item.parse_result, raw_evidence_result=raw_item.index_result, config=_config(tmp_path))

    assert result.semantic_route == "PARSE_FAILED"
    assert result.pfss_write_executed is False
    assert result.generic_write_executed is False
    assert result.issue_index_write_executed is False


def test_raw_evidence_success_is_required(tmp_path: Path):
    raw_item = asyncio.run(_raw_item(0, tmp_path))
    failed_raw = type("FailedRaw", (), {"status": "FAILED", "storage_snapshot_after": raw_item.index_result.storage_snapshot_after})()

    result = execute_semantic_branch(route_decision=raw_item.route_plan, unified_parse_result=raw_item.parse_result, raw_evidence_result=failed_raw, config=_config(tmp_path))

    assert result.status == "RAW_EVIDENCE_REQUIRED"
    assert result.pfss_write_executed is False


def test_generic_graph_is_disabled_by_default(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=False))

    assert all(not item.generic_write_executed for item in suite.results)
    assert suite.report()["results"][2]["generic_write_executed"] is False


def test_generic_smoke_is_isolated_from_pfss(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))
    snapshot = suite.graph_isolation_snapshot

    assert any(item.generic_write_executed for item in suite.results)
    assert snapshot.pfss_generic_node_overlap_count == 0
    assert "generic:Synthetic Generic Topic" in snapshot.generic_node_ids
    assert "generic:Synthetic Generic Topic" not in snapshot.pfss_node_ids


def test_current_live_generic_fallback_is_reported_false(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))

    assert suite.safety_check["live_generic_fallback_extraction_implemented"] is False


def test_branch_execution_is_idempotent(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))

    assert suite.idempotency_passed is True


def test_graph_isolation_snapshot_has_zero_overlap(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))
    snapshot = suite.graph_isolation_snapshot

    assert snapshot.pfss_generic_node_overlap_count == 0
    assert snapshot.pfss_generic_edge_overlap_count == 0
    assert snapshot.pfss_issue_overlap_count == 0
    assert snapshot.namespace_collision_count == 0


def test_report_is_serializable(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))

    json.dumps(suite.report(), sort_keys=True)


def test_live_upload_behavior_is_unchanged(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))
    safety = suite.safety_check

    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_upload_hook_connected"] is False
    assert safety["auto_write_routing_enabled"] is False


def test_no_lightrag_core_modified():
    import subprocess

    result = subprocess.run(["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], check=False, capture_output=True, text=True, timeout=30)
    assert result.stdout.strip() == ""


def test_semantic_branch_second_run_is_idempotent(tmp_path: Path):
    raw_item = asyncio.run(_raw_item(0, tmp_path))
    config = _config(tmp_path)
    first = execute_semantic_branch(route_decision=raw_item.route_plan, unified_parse_result=raw_item.parse_result, raw_evidence_result=raw_item.index_result, config=config)
    second = execute_semantic_branch(route_decision=raw_item.route_plan, unified_parse_result=raw_item.parse_result, raw_evidence_result=raw_item.index_result, config=config)

    assert second.pfss_graph_node_count == first.pfss_graph_node_count
    assert second.pfss_graph_edge_count == first.pfss_graph_edge_count
    assert second.duplicate_semantic_object_count == 0


def test_report_contains_all_exit_gate_fields(tmp_path: Path):
    suite = asyncio.run(execute_fixture_suite(config=_config(tmp_path), generic_isolation_smoke=True))
    report = suite.report()
    required = {
        "sidecar_alignment_passed",
        "endpoint_closure_passed",
        "forbidden_relation_count",
        "duplicate_semantic_object_count",
        "idempotency_passed",
        "issue_object_written_to_pfss_count",
        "artifacts_complete",
        "real_embedding_smoke_status",
    }

    assert required.issubset(report)
    assert report["real_embedding_smoke_status"] == "NOT_RUN"
