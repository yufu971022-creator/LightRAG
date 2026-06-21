from __future__ import annotations

from dataclasses import replace

from lightrag_ext.us_dsl.impact_analysis_executor import execute_impact_analysis
from lightrag_ext.us_dsl.impact_breadth_gate import evaluate_impact_breadth
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import duplicate_impact_output, impact_case, irrelevant_impact_output


def test_duplicate_impacts_are_merged_by_semantic_id() -> None:
    gate = evaluate_impact_breadth(duplicate_impact_output())
    assert not gate.passed
    assert gate.metrics["duplicate_impact_count"] == 1


def test_irrelevant_impacts_are_rejected() -> None:
    gate = evaluate_impact_breadth(irrelevant_impact_output())
    assert not gate.passed
    assert gate.metrics["false_positive_impact_count"] == 1


def test_missing_relevant_dimension_is_detected() -> None:
    output = execute_impact_analysis(impact_case())
    output = replace(output, domain_coverage={**output.domain_coverage, "required_dimensions": ["workflow_state", "missing_dimension"]})
    gate = evaluate_impact_breadth(output)
    assert not gate.passed
    assert "missing_dimension" in gate.metrics["missing_relevant_dimensions"]
