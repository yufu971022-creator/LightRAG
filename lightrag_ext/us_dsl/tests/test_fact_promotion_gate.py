from __future__ import annotations

from lightrag_ext.us_dsl.fact_promotion_gate import evaluate_fact_promotion
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import candidate_fact_output


def test_issue_is_not_fact() -> None:
    assert evaluate_fact_promotion(candidate_fact_output("ISSUE")).metrics["issue_as_fact_count"] == 1


def test_info_only_is_not_fact() -> None:
    assert evaluate_fact_promotion(candidate_fact_output("INFO_ONLY")).metrics["info_only_as_fact_count"] == 1


def test_generic_only_is_not_confirmed_fact() -> None:
    assert evaluate_fact_promotion(candidate_fact_output("GENERIC_ONLY")).metrics["generic_only_as_confirmed_count"] == 1


def test_generic_ner_fact_is_blocked() -> None:
    assert evaluate_fact_promotion(candidate_fact_output("GENERIC_NER")).metrics["generic_ner_fact_hit_count"] == 1
