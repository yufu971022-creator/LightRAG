from __future__ import annotations

from lightrag_ext.us_dsl.functional_qa_contract import OUT_OF_SCOPE_SKILLS, validate_functional_qa_contract
from lightrag_ext.us_dsl.functional_qa_executor import execute_functional_qa
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import qa_case


def test_functional_qa_result_contract() -> None:
    result = execute_functional_qa(qa_case())
    gate = validate_functional_qa_contract(result)
    assert gate.passed
    assert result.query
    assert result.source_citations


def test_qa_and_impact_contracts_require_execution_trace() -> None:
    result = execute_functional_qa(qa_case())
    assert result.execution_trace


def test_us_and_ac_generation_are_out_of_scope() -> None:
    assert OUT_OF_SCOPE_SKILLS["US_GENERATION"] == {"capability_status": "OUT_OF_SCOPE", "executed": False}
    assert OUT_OF_SCOPE_SKILLS["AC_GENERATION"]["executed"] is False
