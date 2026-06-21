from __future__ import annotations

from dataclasses import replace

from lightrag_ext.us_dsl.functional_qa_executor import execute_functional_qa
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import qa_case
from lightrag_ext.us_dsl.version_safety_gate import evaluate_version_safety


def test_historical_rule_is_not_current() -> None:
    output = execute_functional_qa(qa_case())
    bad = replace(output.supporting_facts[0], version_status="HISTORICAL")
    gate = evaluate_version_safety(replace(output, supporting_facts=[bad]))
    assert not gate.passed
    assert gate.metrics["historical_as_current_count"] == 1


def test_version_hard_judgment_is_blocked() -> None:
    output = execute_functional_qa(qa_case())
    output = replace(output, version_context={"resolution_status": "VERSION_REVIEW_REQUIRED", "version_warnings": []}, safe_for_business_use=True)
    gate = evaluate_version_safety(output)
    assert not gate.passed
    assert gate.metrics["version_hard_judgment_error_count"] == 1
