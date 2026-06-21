from __future__ import annotations

from lightrag_ext.us_dsl.impact_analysis_contract import validate_impact_analysis_contract
from lightrag_ext.us_dsl.impact_analysis_executor import execute_impact_analysis
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import impact_case


def test_impact_analysis_result_contract() -> None:
    result = execute_impact_analysis(impact_case())
    gate = validate_impact_analysis_contract(result)
    assert gate.passed
    assert result.primary_change_targets
    assert result.execution_trace
