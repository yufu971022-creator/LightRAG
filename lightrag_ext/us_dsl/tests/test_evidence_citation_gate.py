from __future__ import annotations

from dataclasses import replace

from lightrag_ext.us_dsl.evidence_citation_gate import evaluate_evidence_citation
from lightrag_ext.us_dsl.functional_qa_executor import execute_functional_qa
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import bad_citation, impact_with_bad_path, qa_case, unsupported_fact_output


def test_invalid_citation_is_blocked() -> None:
    output = replace(execute_functional_qa(qa_case()), source_citations=[bad_citation()])
    gate = evaluate_evidence_citation(output)
    assert not gate.passed
    assert gate.metrics["invalid_citation_count"] == 1


def test_unsupported_fact_is_blocked() -> None:
    gate = evaluate_evidence_citation(unsupported_fact_output())
    assert not gate.passed
    assert gate.metrics["unsupported_fact_count"] == 1


def test_unsupported_path_is_not_factual() -> None:
    gate = evaluate_evidence_citation(impact_with_bad_path())
    assert not gate.passed
    assert gate.metrics["unsupported_factual_path_count"] == 1
