from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.unified_e2e_consistency_validator import consistency_passed, validate_cross_layer_consistency
from lightrag_ext.us_dsl.tests.unified_e2e_test_helpers import run


def test_cross_layer_consistency_counts_are_zero(tmp_path: Path) -> None:
    report = run(tmp_path).consistency_report
    assert all(value == 0 for key, value in report.items() if key.endswith("count"))


def test_consistency_validator_passes_for_result(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert consistency_passed(validate_cross_layer_consistency(result.documents, result.queries))


def test_no_untraceable_fact_or_impact(tmp_path: Path) -> None:
    report = run(tmp_path).consistency_report
    assert report["untraceable_fact_count"] == 0
    assert report["untraceable_impact_count"] == 0


def test_no_orphans_or_dangling_edges(tmp_path: Path) -> None:
    report = run(tmp_path).consistency_report
    assert report["orphan_chunk_count"] == 0
    assert report["orphan_vector_count"] == 0
    assert report["dangling_edge_count"] == 0
    assert report["orphan_sidecar_mapping_count"] == 0
