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
from .us_generation_judge import (
    compare_us_generation_results,
    judge_us_generation,
)
from .us_generation_types import (
    ADOPT_ACCEPT_AS_IS,
    ADOPT_ACCEPT_MINOR,
    ADOPT_MAJOR_REVISION,
    ADOPT_REJECT,
    GENERATION_DETERMINISTIC,
    GENERATION_LIVE_LLM,
    MODE_GRAPH_AWARE,
    MODE_LIVE,
    MODE_OFFLINE,
    MODE_TEXT_ONLY,
    PASS,
    USGenerationAbEvalConfig,
    USGenerationAbEvalReport,
    USGenerationCase,
    USGenerationCaseResult,
    USGenerationResult,
)


_RUNTIME_FLAGS = {
    "llm_called": False,
    "storage_written": False,
    "neo4j_connected": False,
}


def run_us_generation_ab_eval(
    *,
    cases: list[USGenerationCase],
    retrieval_index: GraphRetrievalIndexes | None = None,
    retrieval_report_builder=None,
    generator=None,
    judge=None,
    config: USGenerationAbEvalConfig,
    graph_payload: DslKgPayload | None = None,
    llm_callable=None,
) -> USGenerationAbEvalReport:
    if retrieval_index is None:
        retrieval_index, graph_payload = _resolve_retrieval_index_from_builder(
            retrieval_report_builder,
            graph_payload=graph_payload,
        )
    selected_cases = list(cases)[: config.max_cases]
    entity_names = _entity_names(graph_payload, retrieval_index)
    relation_types = _relation_types(graph_payload, retrieval_index)
    case_results: list[USGenerationCaseResult] = []
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
        generator_fn = generator or generate_us_deterministic
        text_us = _generate_us(
            case,
            text_context,
            config=config,
            generator=generator_fn,
            llm_callable=llm_callable,
        )
        graph_us = _generate_us(
            case,
            graph_context,
            config=config,
            generator=generator_fn,
            llm_callable=llm_callable,
        )
        judge_fn = judge or judge_us_generation
        text_judgement = judge_fn(case, text_us, text_context)
        graph_judgement = judge_fn(case, graph_us, graph_context)
        missing_graph_objects = _missing_graph_objects(case, entity_names, relation_types)
        comparison = compare_us_generation_results(
            case=case,
            text_judgement=text_judgement,
            graph_judgement=graph_judgement,
            graph_path_used=graph_us.graph_path_used,
            graph_missing_expected_objects=missing_graph_objects,
        )
        case_results.append(
            USGenerationCaseResult(
                case=case,
                graph_coverage_status=_case_coverage_status(case, entity_names, relation_types),
                missing_graph_objects=missing_graph_objects,
                text_result=text_us,
                graph_result=graph_us,
                text_judgement=text_judgement,
                graph_judgement=graph_judgement,
                comparison=comparison,
            )
        )
    return _report(case_results, config=config)


def generate_us_deterministic(
    case: USGenerationCase,
    context: GraphAnswerContext,
) -> USGenerationResult:
    cited_evidence = _select_cited_evidence(context)
    cited_evidence_ids = [item.evidence_id for item in cited_evidence]
    graph_path_used = context.mode == MODE_GRAPH_AWARE and bool(context.graph_paths)
    generated_sections = _sections_for_generation(case, context)
    markdown = _us_markdown(
        case,
        context,
        generated_sections=generated_sections,
        cited_evidence=cited_evidence,
        graph_path_used=graph_path_used,
    )
    return USGenerationResult(
        case_id=case.case_id,
        mode=context.mode,
        generated_us_markdown=markdown,
        generated_sections=generated_sections,
        cited_evidence_ids=cited_evidence_ids,
        cited_source_us_ids=_unique(
            [item.source_us_id for item in cited_evidence if item.source_us_id]
        ),
        cited_text_unit_ids=_unique(
            [item.text_unit_id for item in cited_evidence if item.text_unit_id]
        ),
        cited_graph_paths=[path.path_id for path in context.graph_paths] if graph_path_used else [],
        unsupported_claims=[],
        invalid_citations=[],
        graph_path_used=graph_path_used,
        generation_mode=GENERATION_DETERMINISTIC,
        issues=[],
    )


def generate_us_with_llm(
    case: USGenerationCase,
    context: GraphAnswerContext,
    *,
    live_env_var: str | None,
    llm_callable=None,
) -> USGenerationResult:
    if not live_env_var or os.getenv(live_env_var) != "1":
        return generate_us_deterministic(case, context)
    if llm_callable is None:
        result = generate_us_deterministic(case, context)
        result.generation_mode = GENERATION_LIVE_LLM
        result.issues.append("LIVE_LLM_UNAVAILABLE")
        return result
    _RUNTIME_FLAGS["llm_called"] = True
    text = str(llm_callable(prompt=_live_prompt(case, context), max_tokens=1600))
    cited_ids = [item.evidence_id for item in context.evidence_items if item.evidence_id in text]
    return USGenerationResult(
        case_id=case.case_id,
        mode=context.mode,
        generated_us_markdown=text,
        generated_sections=_sections_from_markdown(text),
        cited_evidence_ids=cited_ids,
        cited_source_us_ids=_source_us_ids_for_citations(cited_ids, context),
        cited_text_unit_ids=_text_unit_ids_for_citations(cited_ids, context),
        cited_graph_paths=[path.path_id for path in context.graph_paths if path.path_id in text],
        graph_path_used=any(path.path_id in text for path in context.graph_paths),
        generation_mode=GENERATION_LIVE_LLM,
    )


def serialize_us_generation_ab_eval_report(report: USGenerationAbEvalReport) -> dict[str, Any]:
    return asdict(report)


def get_us_generation_runtime_flags() -> dict[str, bool]:
    return dict(_RUNTIME_FLAGS)


def _query_from_case(case: USGenerationCase) -> GraphRetrievalQuery:
    return GraphRetrievalQuery(
        query_id=case.case_id,
        query_text=case.user_request,
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


def _contexts_from_comparison(retrieval_comparison, *, source: str):
    report = GraphRetrievalEvaluationReport(
        source=source,
        query_count=1,
        improved_count=1 if retrieval_comparison.improvement_label == IMPROVED else 0,
        same_count=1 if retrieval_comparison.improvement_label == SAME else 0,
        degraded_count=1 if retrieval_comparison.improvement_label == DEGRADED else 0,
        inconclusive_count=1 if retrieval_comparison.improvement_label == INCONCLUSIVE else 0,
        avg_entity_recall_delta=retrieval_comparison.entity_recall_delta,
        avg_relation_recall_delta=retrieval_comparison.relation_recall_delta,
        avg_evidence_coverage_delta=retrieval_comparison.evidence_coverage_delta,
        avg_source_span_coverage_delta=retrieval_comparison.source_span_coverage_delta,
        avg_graph_path_delta=float(retrieval_comparison.graph_path_delta),
        recommended_next_step="BUILD_US_GENERATION_CONTEXT",
        comparison_results=[retrieval_comparison],
    )
    text_contexts, graph_contexts = build_answer_contexts_from_retrieval_results(report)
    return text_contexts[0], graph_contexts[0]


def _generate_us(
    case: USGenerationCase,
    context: GraphAnswerContext,
    *,
    config: USGenerationAbEvalConfig,
    generator,
    llm_callable=None,
) -> USGenerationResult:
    if config.mode == MODE_LIVE and config.allow_live_llm:
        return generate_us_with_llm(
            case,
            context,
            live_env_var=config.live_env_var,
            llm_callable=llm_callable,
        )
    return generator(case, context)


def _sections_for_generation(
    case: USGenerationCase,
    context: GraphAnswerContext,
) -> list[str]:
    core = [
        "title",
        "role_goal_value",
        "given_when_then",
        "business_rules",
        "acceptance_criteria",
        "source_evidence",
        "open_questions",
    ]
    if context.mode == MODE_GRAPH_AWARE:
        return _unique([*core, *case.expected_us_sections])
    text_supported = [
        section
        for section in case.expected_us_sections
        if section in {"role_goal_value", "given_when_then", "business_rules", "dfx", "acceptance_criteria", "source_evidence"}
    ]
    return _unique([*core, *text_supported])


def _us_markdown(
    case: USGenerationCase,
    context: GraphAnswerContext,
    *,
    generated_sections: list[str],
    cited_evidence: list[EvidenceItem],
    graph_path_used: bool,
) -> str:
    evidence_refs = ", ".join(item.evidence_id for item in cited_evidence) or "none"
    entity_text = "、".join(case.expected_entities) or "当前证据未指定实体"
    relation_text = "、".join(case.expected_relations) or "当前证据未指定关系"
    lines = [
        f"# {case.user_request}",
        "",
        "## As a / I Want / So That",
        "- As a: 业务用户或系统实施人员",
        f"- I Want: {case.user_request}",
        "- So That: 规则可被评审并能追溯到 source evidence。",
        "",
        "## Given / When / Then",
        "- Given: 已有候选级 source evidence 可用。",
        "- When: 需要生成或优化用户故事。",
        "- Then: 生成的规则必须引用 evidence，不得声明为正式已确认事实。",
        "",
        "## Business Rules",
        f"- 覆盖对象：{entity_text}。Evidence: {evidence_refs}",
        f"- 覆盖关系：{relation_text}。Evidence: {evidence_refs}",
    ]
    for section in generated_sections:
        lines.extend(_optional_section(section, case, evidence_refs))
    lines.extend(
        [
            "",
            "## Acceptance Criteria",
            "- 所有关键规则都有 source evidence 引用。",
            "- 无证据内容进入 Open Questions / To Be Confirmed。",
            "",
            "## Source Evidence",
            *[
                (
                    f"- {item.evidence_id}: sourceUsId={item.source_us_id}, "
                    f"textUnitId={item.text_unit_id}, textHash={item.text_hash}"
                )
                for item in cited_evidence
            ],
            "",
            "## Open Questions / To Be Confirmed",
        ]
    )
    if case.generation_task_type == "VERSION_REVIEW_US":
        lines.append("- 当前版本关系证据不足，需基于 latestFlag / supersedes / versionStatus 或人工确认。")
    else:
        lines.append("- 对 evidence 未覆盖的业务细节保持待确认。")
    if context.mode == MODE_GRAPH_AWARE and graph_path_used:
        lines.extend(["", "## Graph Paths"])
        for path in context.graph_paths:
            lines.append(
                f"- {path.path_id}: {' -> '.join(path.nodes)} "
                f"({', '.join(path.relation_sequence)})"
            )
    return "\n".join(lines)


def _optional_section(section: str, case: USGenerationCase, evidence_refs: str) -> list[str]:
    headings = {
        "field_specs": "Field Specs",
        "state_transitions": "State Transitions",
        "task_rules": "Task Rules",
        "api_integration": "API / Integration",
        "report_query": "Report / Query",
        "access_audit": "Access / Audit",
        "migration": "Migration / Initialization",
        "dfx": "DFX / Exception Handling",
    }
    if section not in headings:
        return []
    return [
        "",
        f"## {headings[section]}",
        f"- 根据当前证据整理该部分；Evidence: {evidence_refs}",
    ]


def _select_cited_evidence(context: GraphAnswerContext) -> list[EvidenceItem]:
    if context.mode == MODE_TEXT_ONLY:
        return context.evidence_items[:3]
    graph_items = [item for item in context.evidence_items if item.from_graph]
    text_items = [item for item in context.evidence_items if not item.from_graph]
    return [*graph_items[:4], *text_items[:2]][:6]


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
    case: USGenerationCase,
    entity_names: set[str],
    relation_types: set[str],
) -> list[str]:
    missing = [entity for entity in case.expected_entities if entity not in entity_names]
    missing.extend(
        relation for relation in case.expected_relations if relation not in relation_types
    )
    return missing


def _case_coverage_status(
    case: USGenerationCase,
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
    case_results: list[USGenerationCaseResult],
    *,
    config: USGenerationAbEvalConfig,
) -> USGenerationAbEvalReport:
    labels = [item.comparison.improvement_label for item in case_results]
    text_scores = [item.text_judgement.score for item in case_results]
    graph_scores = [item.graph_judgement.score for item in case_results]
    risks = _risks(case_results)
    return USGenerationAbEvalReport(
        module_name=config.module_name,
        case_pack_name=config.case_pack_name,
        case_count=len(case_results),
        text_only_pass_count=sum(1 for item in case_results if item.text_judgement.result == PASS),
        graph_aware_pass_count=sum(1 for item in case_results if item.graph_judgement.result == PASS),
        improved_count=labels.count(IMPROVED),
        same_count=labels.count(SAME),
        degraded_count=labels.count(DEGRADED),
        inconclusive_count=labels.count(INCONCLUSIVE),
        avg_text_score=_avg(text_scores),
        avg_graph_score=_avg(graph_scores),
        avg_score_delta=_avg(item.comparison.score_delta for item in case_results),
        avg_evidence_grounding_delta=_avg(item.comparison.evidence_grounding_delta for item in case_results),
        avg_source_span_delta=_avg(item.comparison.source_span_delta for item in case_results),
        avg_unsupported_claim_delta=_avg(item.comparison.unsupported_claim_delta for item in case_results),
        avg_structure_completeness_delta=_avg(item.comparison.structure_completeness_delta for item in case_results),
        avg_business_rule_coverage_delta=_avg(item.comparison.business_rule_coverage_delta for item in case_results),
        avg_review_readiness_delta=_avg(item.comparison.review_readiness_delta for item in case_results),
        graph_path_used_count=sum(1 for item in case_results if item.graph_result.graph_path_used),
        accept_as_is_count=sum(1 for item in case_results if item.graph_judgement.adoption_level == ADOPT_ACCEPT_AS_IS),
        accept_with_minor_edits_count=sum(1 for item in case_results if item.graph_judgement.adoption_level == ADOPT_ACCEPT_MINOR),
        need_major_revision_count=sum(1 for item in case_results if item.graph_judgement.adoption_level == ADOPT_MAJOR_REVISION),
        reject_count=sum(1 for item in case_results if item.graph_judgement.adoption_level == ADOPT_REJECT),
        recommended_next_step=_recommended_next_step(labels, risks),
        risks=risks,
        case_results=case_results,
        llm_called=_RUNTIME_FLAGS["llm_called"],
        storage_written=_RUNTIME_FLAGS["storage_written"],
        neo4j_connected=_RUNTIME_FLAGS["neo4j_connected"],
    )


def _risks(case_results: list[USGenerationCaseResult]) -> list[str]:
    risks: list[str] = []
    if any(item.comparison.improvement_label == DEGRADED for item in case_results):
        risks.append("At least one US generation case degraded.")
    if any(item.graph_judgement.unsupported_claim_count for item in case_results):
        risks.append("Graph-aware US generation produced unsupported claims.")
    if any(item.graph_judgement.invalid_citation_count for item in case_results):
        risks.append("Graph-aware US generation produced invalid citations.")
    if any(item.case.generation_task_type == "VERSION_REVIEW_US" and item.comparison.improvement_label == INCONCLUSIVE for item in case_results):
        risks.append("Version relation coverage is incomplete; version case remains inconclusive.")
    return risks


def _recommended_next_step(labels: list[str], risks: list[str]) -> str:
    if labels.count(DEGRADED):
        return "TUNE_US_GENERATION_GUARDRAILS"
    if any("unsupported" in risk.lower() for risk in risks):
        return "FIX_US_GENERATION_GROUNDING"
    if any("version" in risk.lower() for risk in risks):
        return "FIX_VERSION_RELATION_COVERAGE"
    if labels.count(IMPROVED) > 0:
        return "PREPARE_IMPACT_ANALYSIS_AB_EVAL"
    return "TUNE_US_GENERATION_RETRIEVAL"


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


def _live_prompt(case: USGenerationCase, context: GraphAnswerContext) -> str:
    return "\n".join(
        [
            "Generate a grounded user story using only the provided evidence.",
            f"Request: {case.user_request}",
            f"Expected sections: {', '.join(case.expected_us_sections)}",
            "Evidence:",
            *[f"- {item.evidence_id}: {item.evidence_text}" for item in context.evidence_items],
        ]
    )


def _sections_from_markdown(text: str) -> list[str]:
    sections: list[str] = []
    lowered = text.lower()
    aliases = {
        "role_goal_value": "as a",
        "given_when_then": "given",
        "business_rules": "business rules",
        "acceptance_criteria": "acceptance criteria",
        "source_evidence": "source evidence",
        "open_questions": "open questions",
        "dfx": "dfx",
    }
    for key, token in aliases.items():
        if token in lowered:
            sections.append(key)
    return sections


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
    "generate_us_deterministic",
    "generate_us_with_llm",
    "get_us_generation_runtime_flags",
    "run_us_generation_ab_eval",
    "serialize_us_generation_ab_eval_report",
]
