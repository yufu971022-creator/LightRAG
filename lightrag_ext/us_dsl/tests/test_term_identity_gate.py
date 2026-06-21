from __future__ import annotations

from dataclasses import replace

from lightrag_ext.us_dsl.functional_qa_executor import execute_functional_qa
from lightrag_ext.us_dsl.term_identity_gate import evaluate_term_identity
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import qa_case


def test_candidate_alias_is_not_confirmed_fact() -> None:
    output = execute_functional_qa(qa_case())
    bad = replace(output.supporting_facts[0], object_id_or_value="candidate_alias")
    output = replace(output, supporting_facts=[bad], term_identity_context={"confirmed_alias_groups": [], "candidate_aliases": ["candidate_alias"]})
    gate = evaluate_term_identity(output)
    assert not gate.passed
    assert gate.metrics["candidate_alias_as_fact_count"] == 1
