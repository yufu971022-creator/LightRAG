from __future__ import annotations

import json

from lightrag_ext.us_dsl.graph_answer_eval import (
    build_answer_contexts_from_retrieval_results,
    build_lc_mini_graph_answer_evaluation_report,
    compare_text_vs_graph_answers,
    evaluate_answer_grounding,
    generate_answer_deterministic,
    generate_answer_with_llm,
    get_graph_answer_runtime_flags,
    serialize_graph_answer_evaluation_report,
)
from lightrag_ext.us_dsl.graph_answer_types import AnswerGenerationResult
from lightrag_ext.us_dsl.graph_retrieval_eval import (
    build_lc_mini_graph_retrieval_evaluation_report,
)
from lightrag_ext.us_dsl.graph_retrieval_types import (
    DEGRADED,
    IMPROVED,
    MODE_GRAPH_AWARE,
    MODE_TEXT_ONLY,
    GraphRetrievalQuery,
)


def test_build_answer_contexts_from_lc_retrieval_report():
    retrieval_report = build_lc_mini_graph_retrieval_evaluation_report(max_queries=3)

    text_contexts, graph_contexts = build_answer_contexts_from_retrieval_results(
        retrieval_report,
        max_queries=3,
    )

    assert text_contexts
    assert graph_contexts
    assert all(context.text_hits for context in text_contexts)
    assert all(context.node_hits for context in graph_contexts)
    assert all(context.edge_hits for context in graph_contexts)
    assert all(context.path_hits for context in graph_contexts)
    assert all(
        item.source_us_id and item.text_hash
        for context in [*text_contexts, *graph_contexts]
        for item in context.evidence_items
    )


def test_deterministic_text_only_answer():
    text_context, _ = _first_context_pair()

    answer = generate_answer_deterministic(text_context)

    assert answer.mode == MODE_TEXT_ONLY
    assert answer.graph_path_used is False
    assert answer.cited_evidence_ids
    assert "text-only 模式未使用图谱路径" in answer.answer_text


def test_deterministic_graph_aware_answer_uses_path():
    _, graph_context = _first_context_pair()

    answer = generate_answer_deterministic(graph_context)

    assert answer.mode == MODE_GRAPH_AWARE
    assert answer.graph_path_used is True
    assert answer.cited_graph_paths
    assert any(item.from_graph for item in graph_context.evidence_items)
    assert answer.cited_evidence_ids


def test_grounding_detects_unsupported_claim():
    _, graph_context = _first_context_pair()
    answer = AnswerGenerationResult(
        query_id=graph_context.query_id,
        mode=MODE_GRAPH_AWARE,
        answer_text=f"结论：NonexistentEntity 参与流程。{graph_context.evidence_items[0].evidence_id}",
        cited_evidence_ids=[graph_context.evidence_items[0].evidence_id],
    )

    grounding = evaluate_answer_grounding(answer, graph_context)

    assert grounding.unsupported_claim_count > 0
    assert grounding.grounding_passed is False


def test_grounding_detects_invalid_citation():
    _, graph_context = _first_context_pair()
    answer = AnswerGenerationResult(
        query_id=graph_context.query_id,
        mode=MODE_GRAPH_AWARE,
        answer_text="结论：引用了不存在证据。EV-bad-99",
        cited_evidence_ids=["EV-bad-99"],
    )

    grounding = evaluate_answer_grounding(answer, graph_context)

    assert grounding.invalid_citation_count > 0
    assert grounding.grounding_passed is False


def test_compare_graph_answer_improved():
    text_context, graph_context = _first_context_pair()
    text_answer = generate_answer_deterministic(text_context)
    graph_answer = generate_answer_deterministic(graph_context)
    query = _query_from_context(graph_context)

    metrics = compare_text_vs_graph_answers(text_answer, graph_answer, query)

    assert metrics.improvement_label == IMPROVED
    assert metrics.graph_path_usage_delta == 1
    assert metrics.expected_relation_coverage_delta >= 0


def test_compare_graph_answer_degraded_if_hallucinates():
    text_context, graph_context = _first_context_pair()
    text_answer = generate_answer_deterministic(text_context)
    graph_answer = generate_answer_deterministic(graph_context)
    graph_answer.unsupported_claims.append("NonexistentEntity has no evidence.")
    query = _query_from_context(graph_context)

    metrics = compare_text_vs_graph_answers(text_answer, graph_answer, query)

    assert metrics.improvement_label == DEGRADED


def test_no_llm_called_by_default(monkeypatch):
    monkeypatch.delenv("LIGHTRAG_DSL_RUN_GRAPH_AWARE_ANSWER_LIVE", raising=False)
    _, graph_context = _first_context_pair()

    generate_answer_deterministic(graph_context)

    assert get_graph_answer_runtime_flags()["llm_called"] is False


def test_live_answer_generation_skips_without_env(monkeypatch):
    monkeypatch.delenv("LIGHTRAG_DSL_RUN_GRAPH_AWARE_ANSWER_LIVE", raising=False)
    _, graph_context = _first_context_pair()
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return "should not run"

    result = generate_answer_with_llm(graph_context, llm_callable=fake_llm)

    assert called["value"] is False
    assert result.issues[0]["code"] == "LIVE_LLM_DISABLED"


def test_report_serializable():
    report = build_lc_mini_graph_answer_evaluation_report(max_queries=3)

    json.dumps(serialize_graph_answer_evaluation_report(report))


def test_lc_graph_answer_eval_report():
    report = build_lc_mini_graph_answer_evaluation_report(max_queries=5)

    assert report.query_count > 0
    assert report.recommended_next_step
    assert report.degraded_count == 0
    assert report.improved_count >= 1


def _first_context_pair():
    retrieval_report = build_lc_mini_graph_retrieval_evaluation_report(max_queries=2)
    text_contexts, graph_contexts = build_answer_contexts_from_retrieval_results(
        retrieval_report,
        max_queries=2,
    )
    return text_contexts[0], graph_contexts[0]


def _query_from_context(context):
    return GraphRetrievalQuery(
        query_id=context.query_id,
        query_text=context.query_text,
        expected_entities=list(context.expected_entities),
        expected_relations=list(context.expected_relations),
        expected_evidence_keywords=list(context.expected_evidence_keywords),
    )
