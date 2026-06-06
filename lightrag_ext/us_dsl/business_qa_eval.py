from __future__ import annotations

from dataclasses import asdict
import os
from typing import Any

from .business_qa_coverage import (
    coverage_label,
    evaluate_business_case_graph_coverage as _evaluate_business_case_graph_coverage,
    serialize_business_qa_graph_coverage_report,
)
from .business_qa_judge import (
    PASS,
    compare_business_qa_answers,
    judge_business_qa_answer,
)
from .business_qa_types import (
    BusinessQaAbEvalConfig,
    BusinessQaAbEvalReport,
    BusinessQaCaseResult,
    BusinessQaGraphCoverageReport,
)
from .graph_answer_eval import (
    build_answer_contexts_from_retrieval_results,
    generate_answer_deterministic,
    generate_answer_with_llm,
)
from .graph_answer_types import AnswerGenerationResult, GraphAnswerContext
from .graph_retrieval_eval import (
    compare_retrieval_results,
    run_graph_aware_retrieval,
    run_text_only_retrieval,
)
from .graph_retrieval_index import GraphRetrievalIndexes
from .graph_retrieval_types import (
    DEGRADED,
    IMPROVED,
    INCONCLUSIVE,
    SAME,
    GraphRetrievalEvaluationReport,
    GraphRetrievalQuery,
    RetrievalComparisonResult,
)
from .kg_payload_types import DslKgPayload


MODE_OFFLINE = "offline"
MODE_LIVE = "live"

_RUNTIME_FLAGS = {
    "llm_called": False,
    "storage_written": False,
    "neo4j_connected": False,
}


def run_business_qa_ab_eval(
    cases: list[Any] | None = None,
    retrieval_index: GraphRetrievalIndexes | None = None,
    *,
    retrieval_report_builder=None,
    answer_generator=None,
    judge=None,
    config: BusinessQaAbEvalConfig,
    graph_payload: DslKgPayload | None = None,
    llm_callable=None,
) -> BusinessQaAbEvalReport:
    if retrieval_index is None:
        retrieval_index, graph_payload = _resolve_retrieval_index_from_builder(
            retrieval_report_builder,
            graph_payload=graph_payload,
        )
    selected_cases = list(cases or [])[: config.max_cases]
    entity_names = _entity_names(graph_payload, retrieval_index)
    relation_types = _relation_types(graph_payload, retrieval_index)
    coverage_report = (
        evaluate_business_case_graph_coverage(selected_cases, graph_payload)
        if graph_payload is not None
        else None
    )
    case_results: list[BusinessQaCaseResult] = []

    for case in selected_cases:
        query = _query_from_case(case)
        text_result = run_text_only_retrieval(query, retrieval_index.text_index)
        graph_result = run_graph_aware_retrieval(
            query,
            retrieval_index.text_index,
            retrieval_index.node_index,
            retrieval_index.edge_index,
            retrieval_index.path_index,
        )
        retrieval_comparison = compare_retrieval_results(query, text_result, graph_result)
        text_context, graph_context = _contexts_from_comparison(
            retrieval_comparison,
            source=config.source or config.module_name,
        )
        text_answer = _generate_answer(
            config,
            text_context,
            llm_callable=llm_callable,
            answer_generator=answer_generator,
        )
        graph_answer = _generate_answer(
            config,
            graph_context,
            llm_callable=llm_callable,
            answer_generator=answer_generator,
        )
        judge_fn = judge or judge_business_qa_answer
        text_judgement = judge_fn(case, text_answer, text_context)
        graph_judgement = judge_fn(case, graph_answer, graph_context)
        missing_graph_objects = _missing_graph_objects(case, entity_names, relation_types)
        coverage_status = _case_coverage_status(case, entity_names, relation_types)
        label, reasons = compare_business_qa_answers(
            case=case,
            text_judgement=text_judgement,
            graph_judgement=graph_judgement,
            graph_path_used=graph_answer.graph_path_used,
            graph_missing_expected_objects=missing_graph_objects,
        )
        case_results.append(
            BusinessQaCaseResult(
                case=case,
                graph_coverage_status=coverage_status,
                missing_graph_objects=missing_graph_objects,
                text_answer=text_answer,
                graph_answer=graph_answer,
                text_judgement=text_judgement,
                graph_judgement=graph_judgement,
                improvement_label=label,
                reasons=reasons,
                graph_path_used=graph_answer.graph_path_used,
            )
        )

    return _report(
        case_results,
        config=config,
        coverage_report=coverage_report,
    )


def evaluate_business_case_graph_coverage(
    cases: list[Any],
    graph_payload: DslKgPayload,
) -> BusinessQaGraphCoverageReport:
    return _evaluate_business_case_graph_coverage(cases, graph_payload)


def serialize_business_qa_ab_eval_report(report: BusinessQaAbEvalReport) -> dict[str, Any]:
    return asdict(report)


def get_business_qa_runtime_flags() -> dict[str, bool]:
    return dict(_RUNTIME_FLAGS)


def _query_from_case(case: Any) -> GraphRetrievalQuery:
    return GraphRetrievalQuery(
        query_id=case.case_id,
        query_text=case.question,
        expected_focus=[
            *getattr(case, "expected_entities", []),
            *getattr(case, "expected_relations", []),
            *getattr(case, "expected_evidence_keywords", []),
        ],
        expected_domains=list(getattr(case, "expected_domains", [])),
        expected_sections=list(getattr(case, "expected_sections", [])),
        expected_entities=list(getattr(case, "expected_entities", [])),
        expected_relations=list(getattr(case, "expected_relations", [])),
        expected_evidence_keywords=list(getattr(case, "expected_evidence_keywords", [])),
        level=getattr(case, "level", "L1"),
    )


def _contexts_from_comparison(
    comparison: RetrievalComparisonResult,
    *,
    source: str,
) -> tuple[GraphAnswerContext, GraphAnswerContext]:
    report = GraphRetrievalEvaluationReport(
        source=source,
        query_count=1,
        improved_count=1 if comparison.improvement_label == IMPROVED else 0,
        same_count=1 if comparison.improvement_label == SAME else 0,
        degraded_count=1 if comparison.improvement_label == DEGRADED else 0,
        inconclusive_count=1 if comparison.improvement_label == INCONCLUSIVE else 0,
        avg_entity_recall_delta=comparison.entity_recall_delta,
        avg_relation_recall_delta=comparison.relation_recall_delta,
        avg_evidence_coverage_delta=comparison.evidence_coverage_delta,
        avg_source_span_coverage_delta=comparison.source_span_coverage_delta,
        avg_graph_path_delta=float(comparison.graph_path_delta),
        recommended_next_step="BUILD_ANSWER_CONTEXT",
        risks=[],
        comparison_results=[comparison],
    )
    text_contexts, graph_contexts = build_answer_contexts_from_retrieval_results(report)
    return text_contexts[0], graph_contexts[0]


def _generate_answer(
    config: BusinessQaAbEvalConfig,
    context: GraphAnswerContext,
    *,
    llm_callable=None,
    answer_generator=None,
) -> AnswerGenerationResult:
    if answer_generator is not None:
        return answer_generator(context)
    if config.mode == MODE_LIVE:
        env_enabled = bool(config.live_env_var and os.getenv(config.live_env_var) == "1")
        if config.allow_live_llm and env_enabled:
            result = generate_answer_with_llm(context, llm_callable=llm_callable)
            if result.generation_mode == "live_llm" and not result.issues:
                _RUNTIME_FLAGS["llm_called"] = True
            return result
        return generate_answer_deterministic(context)
    return generate_answer_deterministic(context)


def _resolve_retrieval_index_from_builder(
    retrieval_report_builder,
    *,
    graph_payload: DslKgPayload | None,
) -> tuple[GraphRetrievalIndexes, DslKgPayload | None]:
    if retrieval_report_builder is None:
        raise ValueError("retrieval_index or retrieval_report_builder is required.")
    built = retrieval_report_builder()
    if isinstance(built, tuple):
        retrieval_index = built[0]
        next_graph_payload = built[1] if len(built) > 1 else graph_payload
        return retrieval_index, next_graph_payload
    return built, graph_payload


def _entity_names(
    graph_payload: DslKgPayload | None,
    retrieval_index: GraphRetrievalIndexes,
) -> set[str]:
    if graph_payload is not None:
        return {entity.entity_name for entity in graph_payload.entities}
    return {record.entity_name for record in retrieval_index.node_index.records}


def _relation_types(
    graph_payload: DslKgPayload | None,
    retrieval_index: GraphRetrievalIndexes,
) -> set[str]:
    if graph_payload is not None:
        return {relationship.keywords for relationship in graph_payload.relationships}
    return {record.relation_type for record in retrieval_index.edge_index.records}


def _missing_graph_objects(
    case: Any,
    entity_names: set[str],
    relation_types: set[str],
) -> list[str]:
    missing = [
        entity
        for entity in getattr(case, "expected_entities", [])
        if entity not in entity_names
    ]
    missing.extend(
        relation
        for relation in getattr(case, "expected_relations", [])
        if relation not in relation_types
    )
    return missing


def _case_coverage_status(
    case: Any,
    entity_names: set[str],
    relation_types: set[str],
) -> str:
    return coverage_label(
        list(getattr(case, "expected_entities", [])),
        list(getattr(case, "expected_relations", [])),
        [
            item
            for item in getattr(case, "expected_entities", [])
            if item not in entity_names
        ],
        [
            item
            for item in getattr(case, "expected_relations", [])
            if item not in relation_types
        ],
    ).lower()


def _report(
    case_results: list[BusinessQaCaseResult],
    *,
    config: BusinessQaAbEvalConfig,
    coverage_report: BusinessQaGraphCoverageReport | None,
) -> BusinessQaAbEvalReport:
    text_scores = [item.text_judgement.score for item in case_results]
    graph_scores = [item.graph_judgement.score for item in case_results]
    labels = [item.improvement_label for item in case_results]
    avg_text = _avg(text_scores)
    avg_graph = _avg(graph_scores)
    unsupported_deltas = [
        item.graph_judgement.unsupported_claim_count
        - item.text_judgement.unsupported_claim_count
        for item in case_results
    ]
    risks = _risks(case_results)
    return BusinessQaAbEvalReport(
        source=config.source or config.module_name,
        module_name=config.module_name,
        case_pack_name=config.case_pack_name,
        case_count=len(case_results),
        text_only_pass_count=sum(
            1 for item in case_results if item.text_judgement.result == PASS
        ),
        graph_aware_pass_count=sum(
            1 for item in case_results if item.graph_judgement.result == PASS
        ),
        improved_count=labels.count(IMPROVED),
        same_count=labels.count(SAME),
        degraded_count=labels.count(DEGRADED),
        inconclusive_count=labels.count(INCONCLUSIVE),
        avg_text_score=avg_text,
        avg_graph_score=avg_graph,
        avg_score_delta=avg_graph - avg_text,
        avg_evidence_grounding_delta=_avg(
            item.graph_judgement.evidence_grounding_score
            - item.text_judgement.evidence_grounding_score
            for item in case_results
        ),
        avg_source_span_delta=_avg(
            item.graph_judgement.source_span_score
            - item.text_judgement.source_span_score
            for item in case_results
        ),
        avg_unsupported_claim_delta=_avg(unsupported_deltas),
        graph_path_used_count=sum(1 for item in case_results if item.graph_path_used),
        cases_with_invalid_citation=sum(
            1
            for item in case_results
            if item.text_judgement.invalid_citation_count
            or item.graph_judgement.invalid_citation_count
        ),
        cases_with_candidate_as_confirmed=sum(
            1
            for item in case_results
            if item.text_judgement.candidate_as_confirmed_count
            or item.graph_judgement.candidate_as_confirmed_count
        ),
        recommended_next_step=_recommended_next_step(
            labels=labels,
            avg_score_delta=avg_graph - avg_text,
            avg_unsupported_claim_delta=_avg(unsupported_deltas),
            risks=risks,
        ),
        risks=risks,
        coverage_report=coverage_report,
        case_results=case_results,
        llm_called=_RUNTIME_FLAGS["llm_called"],
        storage_written=_RUNTIME_FLAGS["storage_written"],
        neo4j_connected=_RUNTIME_FLAGS["neo4j_connected"],
    )


def _risks(case_results: list[BusinessQaCaseResult]) -> list[str]:
    risks: list[str] = []
    if any(item.improvement_label == DEGRADED for item in case_results):
        risks.append("At least one business QA case degraded.")
    if any(item.graph_judgement.unsupported_claim_count for item in case_results):
        risks.append("Graph-aware answer produced unsupported claims.")
    if any(item.graph_judgement.invalid_citation_count for item in case_results):
        risks.append("Graph-aware answer produced invalid citations.")
    if any(item.graph_judgement.candidate_as_confirmed_count for item in case_results):
        risks.append("Graph-aware answer phrased Candidate as Confirmed.")
    if sum(1 for item in case_results if item.improvement_label == INCONCLUSIVE) >= 4:
        risks.append("Many cases are outside current graph subset coverage.")
    return risks


def _recommended_next_step(
    *,
    labels: list[str],
    avg_score_delta: float,
    avg_unsupported_claim_delta: float,
    risks: list[str],
) -> str:
    if labels.count(DEGRADED) > 0:
        return "TUNE_GRAPH_ANSWER_GUARDRAILS"
    if avg_unsupported_claim_delta > 0:
        return "FIX_ANSWER_GROUNDING"
    if any("Many cases" in risk for risk in risks):
        return "EXPAND_GRAPH_SUBSET_BEFORE_EVAL"
    if (
        labels.count(DEGRADED) == 0
        and labels.count(IMPROVED) > 0
        and labels.count(INCONCLUSIVE) <= 3
        and avg_score_delta >= 0
    ):
        return "PREPARE_US_GENERATION_AB_EVAL"
    return "TUNE_GRAPH_RETRIEVAL_EVIDENCE"


def _ratio(covered: int, total: int) -> float:
    if total == 0:
        return 1.0
    return covered / total


def _avg(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


__all__ = [
    "MODE_LIVE",
    "MODE_OFFLINE",
    "evaluate_business_case_graph_coverage",
    "get_business_qa_runtime_flags",
    "run_business_qa_ab_eval",
    "serialize_business_qa_ab_eval_report",
    "serialize_business_qa_graph_coverage_report",
]
