from __future__ import annotations

from lightrag_ext.us_dsl.multi_module_eval_types import CaseRetrievalResult
from lightrag_ext.us_dsl.retrieval_effectiveness_metrics import compute_effectiveness_metrics
from lightrag_ext.us_dsl.tests.multi_module_eval_test_helpers import case_obj, hit_for


def test_evidence_recall_at_k() -> None:
    case = case_obj()
    metrics = compute_effectiveness_metrics([case], [hit_for(case)])
    assert metrics.evidence_recall_at_k == 1.0


def test_evidence_precision_at_k() -> None:
    case = case_obj()
    metrics = compute_effectiveness_metrics([case], [hit_for(case)])
    assert metrics.evidence_precision_at_k == 1.0


def test_entity_and_relation_recall() -> None:
    case = case_obj()
    metrics = compute_effectiveness_metrics([case], [hit_for(case)])
    assert metrics.entity_recall_at_k == 1.0
    assert metrics.relation_recall_at_k == 1.0


def test_required_dimension_coverage() -> None:
    case = case_obj(one_to_n=True)
    metrics = compute_effectiveness_metrics([case], [hit_for(case)])
    assert metrics.required_dimension_coverage == 1.0


def test_graph_path_coverage() -> None:
    case = case_obj()
    metrics = compute_effectiveness_metrics([case], [hit_for(case)])
    assert metrics.graph_path_coverage == 1.0


def test_source_span_match() -> None:
    case = case_obj()
    metrics = compute_effectiveness_metrics([case], [hit_for(case)])
    assert metrics.source_span_match_rate == 1.0


def test_cross_language_alias_recall() -> None:
    case = case_obj()
    metrics = compute_effectiveness_metrics([case], [hit_for(case)])
    assert metrics.cross_language_alias_recall == 1.0


def test_text_only_fallback_success() -> None:
    case = case_obj()
    object.__setattr__(case, "task_type", "DESIGN_CONTEXT")
    result = CaseRetrievalResult(case.case_id, case.module_code, "candidate", [])
    metrics = compute_effectiveness_metrics([case], [result])
    assert metrics.text_only_fallback_success_rate == 1.0
