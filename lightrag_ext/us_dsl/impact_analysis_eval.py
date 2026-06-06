from __future__ import annotations

from dataclasses import asdict
import os
from typing import Any

from .business_qa_coverage import coverage_label
from .graph_answer_eval import build_answer_contexts_from_retrieval_results
from .graph_answer_types import EvidenceItem, GraphAnswerContext
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
)
from .kg_payload_types import DslKgPayload
from .impact_analysis_judge import (
    compare_impact_analysis_results,
    judge_impact_analysis,
)
from .impact_analysis_types import (
    GENERATION_DETERMINISTIC,
    GENERATION_LIVE_LLM,
    MODE_GRAPH_AWARE,
    MODE_LIVE,
    MODE_OFFLINE,
    MODE_TEXT_ONLY,
    PASS,
    ImpactAnalysisAbEvalConfig,
    ImpactAnalysisAbEvalReport,
    ImpactAnalysisCase,
    ImpactAnalysisCaseResult,
    ImpactAnalysisResult,
)


_RUNTIME_FLAGS = {
    "llm_called": False,
    "storage_written": False,
    "neo4j_connected": False,
}


def run_impact_analysis_ab_eval(
    *,
    cases: list[ImpactAnalysisCase],
    retrieval_index: GraphRetrievalIndexes,
    config: ImpactAnalysisAbEvalConfig,
    graph_payload: DslKgPayload | None = None,
    generator=None,
    judge=None,
    llm_callable=None,
) -> ImpactAnalysisAbEvalReport:
    selected_cases = list(cases)[: config.max_cases]
    entity_names = _entity_names(graph_payload, retrieval_index)
    relation_types = _relation_types(graph_payload, retrieval_index)
    case_results: list[ImpactAnalysisCaseResult] = []
    for case in selected_cases:
        query = _query_from_case(case)
        text_retrieval = run_text_only_retrieval(query, retrieval_index.text_index)
        graph_retrieval = run_graph_aware_retrieval(
            query,
            retrieval_index.text_index,
            retrieval_index.node_index,
            retrieval_index.edge_index,
            retrieval_index.path_index,
        )
        comparison = compare_retrieval_results(query, text_retrieval, graph_retrieval)
        text_context, graph_context = _contexts_from_comparison(
            comparison,
            source=config.source or config.module_name,
        )
        generator_fn = generator or generate_impact_analysis_deterministic
        text_analysis = _generate_impact_analysis(
            case,
            text_context,
            config=config,
            generator=generator_fn,
            llm_callable=llm_callable,
        )
        graph_analysis = _generate_impact_analysis(
            case,
            graph_context,
            config=config,
            generator=generator_fn,
            llm_callable=llm_callable,
        )
        judge_fn = judge or judge_impact_analysis
        text_judgement = judge_fn(case, text_analysis, text_context)
        graph_judgement = judge_fn(case, graph_analysis, graph_context)
        missing_graph_objects = _missing_graph_objects(case, entity_names, relation_types)
        impact_comparison = compare_impact_analysis_results(
            case=case,
            text_judgement=text_judgement,
            graph_judgement=graph_judgement,
            graph_path_used=graph_analysis.graph_path_used,
            graph_missing_expected_objects=missing_graph_objects,
        )
        case_results.append(
            ImpactAnalysisCaseResult(
                case=case,
                graph_coverage_status=_case_coverage_status(case, entity_names, relation_types),
                missing_graph_objects=missing_graph_objects,
                text_result=text_analysis,
                graph_result=graph_analysis,
                text_judgement=text_judgement,
                graph_judgement=graph_judgement,
                comparison=impact_comparison,
            )
        )
    return _report(case_results, config=config)


def generate_impact_analysis_deterministic(
    case: ImpactAnalysisCase,
    context: GraphAnswerContext,
) -> ImpactAnalysisResult:
    cited_evidence = _select_cited_evidence(context)
    graph_path_used = context.mode == MODE_GRAPH_AWARE and bool(context.graph_paths)
    impacted_entities = _impacted_entities(case, context)
    impacted_relations = _impacted_relations(case, context)
    impacted_domains = _impacted_domains(case, context)
    impacted_sections = _impacted_sections(case, context)
    markdown = _impact_markdown(
        case,
        context,
        cited_evidence=cited_evidence,
        impacted_entities=impacted_entities,
        impacted_relations=impacted_relations,
        impacted_domains=impacted_domains,
        impacted_sections=impacted_sections,
        graph_path_used=graph_path_used,
    )
    return ImpactAnalysisResult(
        case_id=case.case_id,
        mode=context.mode,
        analysis_markdown=markdown,
        impacted_entities=impacted_entities,
        impacted_relations=impacted_relations,
        impacted_domains=impacted_domains,
        impacted_sections=impacted_sections,
        cited_evidence_ids=[item.evidence_id for item in cited_evidence],
        cited_source_us_ids=_unique([item.source_us_id for item in cited_evidence if item.source_us_id]),
        cited_text_unit_ids=_unique([item.text_unit_id for item in cited_evidence if item.text_unit_id]),
        cited_graph_paths=[path.path_id for path in context.graph_paths] if graph_path_used else [],
        graph_path_used=graph_path_used,
        generation_mode=GENERATION_DETERMINISTIC,
    )


def generate_impact_analysis_with_llm(
    case: ImpactAnalysisCase,
    context: GraphAnswerContext,
    *,
    live_env_var: str | None,
    llm_callable=None,
) -> ImpactAnalysisResult:
    if not live_env_var or os.getenv(live_env_var) != "1":
        return generate_impact_analysis_deterministic(case, context)
    if llm_callable is None:
        result = generate_impact_analysis_deterministic(case, context)
        result.generation_mode = GENERATION_LIVE_LLM
        result.issues.append("LIVE_LLM_UNAVAILABLE")
        return result
    _RUNTIME_FLAGS["llm_called"] = True
    text = str(llm_callable(prompt=_live_prompt(case, context), max_tokens=1400))
    cited_ids = [item.evidence_id for item in context.evidence_items if item.evidence_id in text]
    return ImpactAnalysisResult(
        case_id=case.case_id,
        mode=context.mode,
        analysis_markdown=text,
        cited_evidence_ids=cited_ids,
        cited_source_us_ids=_source_us_ids_for_citations(cited_ids, context),
        cited_text_unit_ids=_text_unit_ids_for_citations(cited_ids, context),
        cited_graph_paths=[path.path_id for path in context.graph_paths if path.path_id in text],
        graph_path_used=any(path.path_id in text for path in context.graph_paths),
        generation_mode=GENERATION_LIVE_LLM,
    )


def serialize_impact_analysis_ab_eval_report(
    report: ImpactAnalysisAbEvalReport,
) -> dict[str, Any]:
    return asdict(report)


def get_impact_analysis_runtime_flags() -> dict[str, bool]:
    return dict(_RUNTIME_FLAGS)


def _query_from_case(case: ImpactAnalysisCase) -> GraphRetrievalQuery:
    return GraphRetrievalQuery(
        query_id=case.case_id,
        query_text=case.change_request,
        expected_focus=[
            *case.expected_entities,
            *case.expected_relations,
            *case.expected_evidence_keywords,
        ],
        expected_domains=list(case.expected_domains),
        expected_sections=list(case.expected_sections),
        expected_entities=list(case.expected_entities),
        expected_relations=list(case.expected_relations),
        expected_evidence_keywords=list(case.expected_evidence_keywords),
        level=case.level,
    )


def _contexts_from_comparison(comparison, *, source: str):
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
        recommended_next_step="BUILD_IMPACT_CONTEXT",
        comparison_results=[comparison],
    )
    text_contexts, graph_contexts = build_answer_contexts_from_retrieval_results(report)
    return text_contexts[0], graph_contexts[0]


def _generate_impact_analysis(
    case: ImpactAnalysisCase,
    context: GraphAnswerContext,
    *,
    config: ImpactAnalysisAbEvalConfig,
    generator,
    llm_callable=None,
) -> ImpactAnalysisResult:
    if config.mode == MODE_LIVE and config.allow_live_llm:
        return generate_impact_analysis_with_llm(
            case,
            context,
            live_env_var=config.live_env_var,
            llm_callable=llm_callable,
        )
    return generator(case, context)


def _select_cited_evidence(context: GraphAnswerContext) -> list[EvidenceItem]:
    if context.mode == MODE_TEXT_ONLY:
        return context.evidence_items[:3]
    graph_items = [item for item in context.evidence_items if item.from_graph]
    text_items = [item for item in context.evidence_items if not item.from_graph]
    return [*graph_items[:5], *text_items[:2]][:7]


def _impacted_entities(case: ImpactAnalysisCase, context: GraphAnswerContext) -> list[str]:
    if context.mode == MODE_TEXT_ONLY:
        searchable = "\n".join(item.evidence_text for item in context.evidence_items if not item.from_graph)
    else:
        searchable = "\n".join(
            [
                *(item.evidence_text for item in context.evidence_items),
                *(" ".join(path.nodes) for path in context.graph_paths),
            ]
        )
    return [item for item in case.expected_entities if item.lower() in searchable.lower()]


def _impacted_relations(case: ImpactAnalysisCase, context: GraphAnswerContext) -> list[str]:
    if context.mode == MODE_TEXT_ONLY:
        return []
    searchable = "\n".join(
        [
            *(item.linked_relation or "" for item in context.evidence_items),
            *(" ".join(path.relation_sequence) for path in context.graph_paths),
        ]
    )
    return [item for item in case.expected_relations if item.lower() in searchable.lower()]


def _impacted_domains(case: ImpactAnalysisCase, context: GraphAnswerContext) -> list[str]:
    domains = _unique([item.domain_code for item in context.evidence_items if item.domain_code])
    if context.mode == MODE_GRAPH_AWARE:
        return [item for item in case.expected_domains if item in domains or item.lower() in _context_text(context).lower()]
    return [item for item in case.expected_domains if item in domains]


def _impacted_sections(case: ImpactAnalysisCase, context: GraphAnswerContext) -> list[str]:
    sections = _unique([item.section_type for item in context.evidence_items if item.section_type])
    if context.mode == MODE_GRAPH_AWARE:
        return [item for item in case.expected_sections if item in sections or item.lower() in _context_text(context).lower()]
    return [item for item in case.expected_sections if item in sections]


def _impact_markdown(
    case: ImpactAnalysisCase,
    context: GraphAnswerContext,
    *,
    cited_evidence: list[EvidenceItem],
    impacted_entities: list[str],
    impacted_relations: list[str],
    impacted_domains: list[str],
    impacted_sections: list[str],
    graph_path_used: bool,
) -> str:
    evidence_refs = ", ".join(item.evidence_id for item in cited_evidence) or "none"
    lines = [
        f"# Impact Analysis: {case.change_request}",
        "",
        "## Impact Summary",
        f"- Impacted entities: {', '.join(impacted_entities) or '当前证据不足'}",
        f"- Impacted domains: {', '.join(impacted_domains) or '当前证据不足'}",
        f"- Impacted sections: {', '.join(impacted_sections) or '当前证据不足'}",
        "",
        "## Relation / Path Impact",
        f"- Impacted relations: {', '.join(impacted_relations) or '当前证据不足'}",
        "",
        "## Evidence",
        *[
            (
                f"- {item.evidence_id}: sourceUsId={item.source_us_id}, "
                f"textUnitId={item.text_unit_id}, textHash={item.text_hash}"
            )
            for item in cited_evidence
        ],
        "",
        "## Risk and Review",
        "- 所有影响均保持候选级别，并要求基于 evidence 复核。",
    ]
    if context.mode == MODE_GRAPH_AWARE and graph_path_used:
        lines.extend(["", "## Graph Paths"])
        for path in context.graph_paths:
            lines.append(
                f"- {path.path_id}: {' -> '.join(path.nodes)} "
                f"({', '.join(path.relation_sequence)}) Evidence: {evidence_refs}"
            )
    else:
        lines.append("- text-only 模式未使用图谱路径。")
    if case.impact_task_type == "VERSION_IMPACT":
        lines.extend(
            [
                "",
                "## Open Questions / To Be Confirmed",
                "- 当前版本替代证据不足，不能硬判最新规则；需要人工确认。",
            ]
        )
    return "\n".join(lines)


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
    case: ImpactAnalysisCase,
    entity_names: set[str],
    relation_types: set[str],
) -> list[str]:
    missing = [entity for entity in case.expected_entities if entity not in entity_names]
    missing.extend(relation for relation in case.expected_relations if relation not in relation_types)
    return missing


def _case_coverage_status(
    case: ImpactAnalysisCase,
    entity_names: set[str],
    relation_types: set[str],
) -> str:
    return coverage_label(
        list(case.expected_entities),
        list(case.expected_relations),
        [item for item in case.expected_entities if item not in entity_names],
        [item for item in case.expected_relations if item not in relation_types],
    ).lower()


def _report(
    case_results: list[ImpactAnalysisCaseResult],
    *,
    config: ImpactAnalysisAbEvalConfig,
) -> ImpactAnalysisAbEvalReport:
    labels = [item.comparison.improvement_label for item in case_results]
    risks = _risks(case_results)
    return ImpactAnalysisAbEvalReport(
        module_name=config.module_name,
        case_pack_name=config.case_pack_name,
        case_count=len(case_results),
        text_only_pass_count=sum(1 for item in case_results if item.text_judgement.result == PASS),
        graph_aware_pass_count=sum(1 for item in case_results if item.graph_judgement.result == PASS),
        improved_count=labels.count(IMPROVED),
        same_count=labels.count(SAME),
        degraded_count=labels.count(DEGRADED),
        inconclusive_count=labels.count(INCONCLUSIVE),
        avg_text_score=_avg(item.text_judgement.score for item in case_results),
        avg_graph_score=_avg(item.graph_judgement.score for item in case_results),
        avg_score_delta=_avg(item.comparison.score_delta for item in case_results),
        avg_impact_completeness_delta=_avg(item.comparison.impact_completeness_delta for item in case_results),
        avg_relation_path_delta=_avg(item.comparison.relation_path_delta for item in case_results),
        avg_evidence_grounding_delta=_avg(item.comparison.evidence_grounding_delta for item in case_results),
        avg_source_span_delta=_avg(item.comparison.source_span_delta for item in case_results),
        avg_unsupported_claim_delta=_avg(item.comparison.unsupported_claim_delta for item in case_results),
        graph_path_used_count=sum(1 for item in case_results if item.graph_result.graph_path_used),
        cases_with_invalid_citation=sum(
            1 for item in case_results if item.text_judgement.invalid_citation_count or item.graph_judgement.invalid_citation_count
        ),
        cases_with_candidate_as_confirmed=sum(
            1 for item in case_results if item.text_judgement.candidate_as_confirmed_count or item.graph_judgement.candidate_as_confirmed_count
        ),
        recommended_next_step=_recommended_next_step(labels, risks),
        risks=risks,
        case_results=case_results,
        llm_called=_RUNTIME_FLAGS["llm_called"],
        storage_written=_RUNTIME_FLAGS["storage_written"],
        neo4j_connected=_RUNTIME_FLAGS["neo4j_connected"],
    )


def _risks(case_results: list[ImpactAnalysisCaseResult]) -> list[str]:
    risks: list[str] = []
    if any(item.comparison.improvement_label == DEGRADED for item in case_results):
        risks.append("At least one impact analysis case degraded.")
    if any(item.graph_judgement.unsupported_claim_count for item in case_results):
        risks.append("Graph-aware impact analysis produced unsupported claims.")
    if any(item.graph_judgement.invalid_citation_count for item in case_results):
        risks.append("Graph-aware impact analysis produced invalid citations.")
    return risks


def _recommended_next_step(labels: list[str], risks: list[str]) -> str:
    if labels.count(DEGRADED):
        return "TUNE_IMPACT_ANALYSIS_GUARDRAILS"
    if any("unsupported" in risk.lower() for risk in risks):
        return "FIX_IMPACT_ANALYSIS_GROUNDING"
    if labels.count(IMPROVED) > 0:
        return "PREPARE_CROSS_MODULE_IMPACT_ANALYSIS_PILOT"
    return "TUNE_GRAPH_IMPACT_RETRIEVAL"


def _live_prompt(case: ImpactAnalysisCase, context: GraphAnswerContext) -> str:
    return "\n".join(
        [
            "Generate a grounded impact analysis using only provided evidence.",
            f"Change request: {case.change_request}",
            f"Expected dimensions: {', '.join(case.expected_impact_dimensions)}",
            "Evidence:",
            *[f"- {item.evidence_id}: {item.evidence_text}" for item in context.evidence_items],
        ]
    )


def _source_us_ids_for_citations(cited_ids: list[str], context: GraphAnswerContext) -> list[str]:
    evidence_by_id = {item.evidence_id: item for item in context.evidence_items}
    return _unique([
        evidence_by_id[item].source_us_id
        for item in cited_ids
        if item in evidence_by_id and evidence_by_id[item].source_us_id
    ])


def _text_unit_ids_for_citations(cited_ids: list[str], context: GraphAnswerContext) -> list[str]:
    evidence_by_id = {item.evidence_id: item for item in context.evidence_items}
    return _unique([
        evidence_by_id[item].text_unit_id
        for item in cited_ids
        if item in evidence_by_id and evidence_by_id[item].text_unit_id
    ])


def _context_text(context: GraphAnswerContext) -> str:
    return "\n".join(
        [
            context.query_text,
            *(item.evidence_text for item in context.evidence_items),
            *(" ".join(path.nodes + path.relation_sequence) for path in context.graph_paths),
        ]
    )


def _unique(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _avg(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


__all__ = [
    "MODE_LIVE",
    "MODE_OFFLINE",
    "generate_impact_analysis_deterministic",
    "generate_impact_analysis_with_llm",
    "get_impact_analysis_runtime_flags",
    "run_impact_analysis_ab_eval",
    "serialize_impact_analysis_ab_eval_report",
]
