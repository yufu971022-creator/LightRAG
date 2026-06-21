from __future__ import annotations

from dataclasses import replace

from lightrag_ext.us_dsl.functional_qa_executor import execute_functional_qa
from lightrag_ext.us_dsl.insufficient_evidence_gate import evaluate_insufficient_evidence
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import qa_case


def test_insufficient_evidence_gate_blocks_forced_answer() -> None:
    output = execute_functional_qa(qa_case())
    output = replace(output, source_citations=[], answer_status="ANSWERED_WITH_CONFIRMED_EVIDENCE", safe_for_business_use=True)
    gate = evaluate_insufficient_evidence(output)
    assert not gate.passed
    assert gate.metrics["insufficient_evidence_detection_error_count"] == 1
