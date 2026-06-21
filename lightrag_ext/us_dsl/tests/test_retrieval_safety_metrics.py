from __future__ import annotations

from lightrag_ext.us_dsl.retrieval_safety_metrics import compute_retrieval_safety_metrics
from lightrag_ext.us_dsl.tests.multi_module_eval_test_helpers import case_obj, hit_for


def _metric(flag: str) -> object:
    case = case_obj()
    result = hit_for(case, flag=flag)
    return compute_retrieval_safety_metrics([result])


def test_invalid_citation_count() -> None:
    metrics = _metric("has_citation")
    assert metrics.invalid_citation_count == 0
    case = case_obj()
    result = hit_for(case)
    object.__setattr__(result.hits[0], "has_citation", False)
    assert compute_retrieval_safety_metrics([result]).invalid_citation_count == 1


def test_no_evidence_factual_path_count() -> None:
    assert _metric("unsupported_factual_path").unsupported_factual_path_count == 1


def test_issue_as_fact_count() -> None:
    assert _metric("issue_as_fact").issue_as_fact_count == 1


def test_candidate_as_confirmed_count() -> None:
    assert _metric("candidate_as_confirmed").candidate_as_confirmed_count == 1


def test_info_only_as_fact_count() -> None:
    assert _metric("info_only_as_fact").info_only_as_fact_count == 1


def test_generic_graph_override_count() -> None:
    assert _metric("generic_graph_override").generic_graph_override_count == 1


def test_generic_ner_fact_hit_count() -> None:
    assert _metric("generic_ner_fact_hit").generic_ner_fact_hit_count == 1


def test_version_hard_judgment_error_count() -> None:
    assert _metric("version_hard_judgment_error").version_hard_judgment_error_count == 1


def test_missing_version_warning_count() -> None:
    assert _metric("missing_version_warning").missing_version_warning_count == 1
