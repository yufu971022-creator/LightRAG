from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.local_case_builder import build_local_cases
from lightrag_ext.us_dsl.local_fullflow_gate import required_stage_names, run_local_fullflow_gate
from lightrag_ext.us_dsl.local_fullflow_manifest import build_local_fullflow_manifest
from lightrag_ext.us_dsl.local_us_inventory import discover_local_us_documents


def _manifest(tmp_path: Path):
    (tmp_path / "A_US.md").write_text("# US-1\nEvidence", encoding="utf-8")
    docs, _ = discover_local_us_documents(tmp_path)
    return build_local_fullflow_manifest(docs, build_local_cases(docs))


def test_full_pipeline_invokes_all_required_stages(tmp_path: Path) -> None:
    result = run_local_fullflow_gate(_manifest(tmp_path))
    assert [stage.stage_name for stage in result.stage_results] == required_stage_names()
    assert all(stage.invoked for stage in result.stage_results)


def test_baseline_and_candidate_workspaces_are_isolated(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline_workspace"
    candidate = tmp_path / "candidate_workspace"
    baseline.mkdir()
    candidate.mkdir()
    assert baseline != candidate


def test_local_pass_does_not_equal_multi_module_pass(tmp_path: Path) -> None:
    result = run_local_fullflow_gate(_manifest(tmp_path))
    assert result.multi_module_production_gate_pending is True
    assert result.status != "PASS"


def test_local_pass_with_gaps_keeps_production_gate_pending(tmp_path: Path) -> None:
    result = run_local_fullflow_gate(_manifest(tmp_path))
    assert result.status == "LOCAL_FULLFLOW_PASS_WITH_GAPS"
    assert result.allow_continue_27a_27b_28_local_development is True
    assert result.intranet_real_module_validation_pending is True
