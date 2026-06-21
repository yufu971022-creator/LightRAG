from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.tests.unified_e2e_test_helpers import run


def test_quality_gate_runs_inside_pipeline(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert any(event["component"] == "DesignQualityGate27B" for event in result.trace_events)


def test_quality_gate_safety_counts_are_zero(tmp_path: Path) -> None:
    quality = run(tmp_path).quality_summary["fact_safety"]
    assert all(value == 0 for key, value in quality.items() if key.endswith("count"))


def test_direct_indirect_tentative_impact_summary_present(tmp_path: Path) -> None:
    impact = run(tmp_path).quality_summary["impact_analysis"]
    assert impact["direct_impact_recall"] == 1.0
    assert impact["indirect_impact_recall"] == 1.0
    assert impact["tentative_impact_count"] >= 1


def test_max_attempts_observed_not_above_two(tmp_path: Path) -> None:
    repair = run(tmp_path).quality_summary["repair"]
    assert repair["max_attempts_observed"] <= 2
