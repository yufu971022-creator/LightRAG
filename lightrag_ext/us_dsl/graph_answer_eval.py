from __future__ import annotations

from dataclasses import asdict
import os
import re
from typing import Any

from .graph_answer_prompt import build_graph_answer_prompt, build_text_only_answer_prompt
from .graph_answer_types import (
    GENERATION_DETERMINISTIC,
    GENERATION_LIVE_LLM,
    AnswerComparisonMetrics,
    AnswerGenerationResult,
    AnswerGroundingEvaluation,
    EvidenceItem,
    GraphAnswerContext,
    GraphAnswerEvaluationReport,
    GraphPathEvidence,
)
from .graph_retrieval_eval import (
    build_fx_mini_graph_retrieval_evaluation_report,
    build_lc_mini_graph_retrieval_evaluation_report,
)
from .graph_retrieval_types import (
    DEGRADED,
    HIT_EDGE,
    HIT_NODE,
    HIT_PATH,
    HIT_TEXT,
    IMPROVED,
    INCONCLUSIVE,
    MODE_GRAPH_AWARE,
    MODE_TEXT_ONLY,
    SAME,
    GraphRetrievalEvaluationReport,
    GraphRetrievalQuery,
    RetrievalComparisonResult,
    RetrievalHit,
)
from .lc_mini_graph_smoke import LC_SOURCE_NAME


LIVE_ANSWER_ENV = "LIGHTRAG_DSL_RUN_GRAPH_AWARE_ANSWER_LIVE"

_RUNTIME_FLAGS = {
    "llm_called": False,
    "storage_written": False,
    "neo4j_connected": False,
}


def build_answer_contexts_from_retrieval_results(
    retrieval_report: GraphRetrievalEvaluationReport,
    *,
    max_queries: int = 5,
) -> tuple[list[GraphAnswerContext], list[GraphAnswerContext]]:
    text_contexts: list[GraphAnswerContext] = []
    graph_contexts: list[GraphAnswerContext] = []
    for comparison in retrieval_report.comparison_results[:max_queries]:
        text_contexts.append(
            _context_from_result(
                comparison,
                comparison.text_only_result.hits,
                mode=MODE_TEXT_ONLY,
            )
        )
        graph_contexts.append(
            _context_from_result(
                comparison,
                comparison.graph_aware_result.hits,
                mode=MODE_GRAPH_AWARE,
            )
        )
    return text_contexts, graph_contexts


def generate_answer_deterministic(
    context: GraphAnswerContext,
) -> AnswerGenerationResult:
    cited_evidence = _select_cited_evidence(context)
    cited_ids = [item.evidence_id for item in cited_evidence]
    cited_source_us_ids = _unique([item.source_us_id for item in cited_evidence if item.source_us_id])
    cited_text_unit_ids = _unique([item.text_unit_id for item in cited_evidence if item.text_unit_id])
    entity_coverage = _covered_terms_from_context(context.expected_entities, context)
    relation_coverage = _covered_terms_from_context(context.expected_relations, context)
    missing_expected = [
        item
        for item in [*context.expected_entities, *context.expected_relations]
        if item not in entity_coverage and item not in relation_coverage
    ]
    graph_path_used = context.mode == MODE_GRAPH_AWARE and bool(context.graph_paths)
    cited_graph_paths = [path.path_id for path in context.graph_paths] if graph_path_used else []
    answer_text = _deterministic_answer_text(
        context,
        cited_evidence=cited_evidence,
        cited_graph_paths=cited_graph_paths,
        entity_coverage=entity_coverage,
        relation_coverage=relation_coverage,
    )
    return AnswerGenerationResult(
        query_id=context.query_id,
        mode=context.mode,
        answer_text=answer_text,
        cited_evidence_ids=cited_ids,
        cited_source_us_ids=cited_source_us_ids,
        cited_text_unit_ids=cited_text_unit_ids,
        cited_graph_paths=cited_graph_paths,
        unsupported_claims=[],
        missing_expected_items=missing_expected,
        graph_path_used=graph_path_used,
        generation_mode=GENERATION_DETERMINISTIC,
        issues=[],
    )


def generate_answer_with_llm(
    context: GraphAnswerContext,
    *,
    llm_callable=None,
    max_tokens: int = 1200,
) -> AnswerGenerationResult:
    if os.getenv(LIVE_ANSWER_ENV) != "1":
        return AnswerGenerationResult(
            query_id=context.query_id,
            mode=context.mode,
            answer_text="",
            generation_mode=GENERATION_LIVE_LLM,
            issues=[
                {
                    "severity": "INFO",
                    "code": "LIVE_LLM_DISABLED",
                    "message": "Live answer generation is disabled.",
                }
            ],
        )
    if llm_callable is None:
        return AnswerGenerationResult(
            query_id=context.query_id,
            mode=context.mode,
            answer_text="",
            generation_mode=GENERATION_LIVE_LLM,
            issues=[
                {
                    "severity": "INFO",
                    "code": "LIVE_LLM_UNAVAILABLE",
                    "message": "No live LLM callable was provided.",
                }
            ],
        )
    _RUNTIME_FLAGS["llm_called"] = True
    prompt = (
        build_graph_answer_prompt(context)
        if context.mode == MODE_GRAPH_AWARE
        else build_text_only_answer_prompt(context)
    )
    answer_text = str(llm_callable(prompt=prompt, max_tokens=max_tokens))
    cited_ids = _extract_evidence_ids(answer_text)
    grounding = evaluate_answer_grounding(
        AnswerGenerationResult(
            query_id=context.query_id,
            mode=context.mode,
            answer_text=answer_text,
            cited_evidence_ids=cited_ids,
            generation_mode=GENERATION_LIVE_LLM,
        ),
        context,
    )
    return AnswerGenerationResult(
        query_id=context.query_id,
        mode=context.mode,
        answer_text=answer_text,
        cited_evidence_ids=cited_ids,
        cited_source_us_ids=_source_us_ids_for_citations(cited_ids, context),
        cited_text_unit_ids=_text_unit_ids_for_citations(cited_ids, context),
        cited_graph_paths=_extract_path_ids(answer_text),
        unsupported_claims=[
            issue["message"]
            for issue in grounding.issues
            if issue.get("code") == "UNSUPPORTED_CLAIM"
        ],
        graph_path_used=grounding.graph_path_used,
        generation_mode=GENERATION_LIVE_LLM,
        issues=list(grounding.issues),
    )


def evaluate_answer_grounding(
    result: AnswerGenerationResult,
    context: GraphAnswerContext,
) -> AnswerGroundingEvaluation:
    evidence_ids = {item.evidence_id for item in context.evidence_items}
    cited_ids = _unique([*result.cited_evidence_ids, *_extract_evidence_ids(result.answer_text)])
    invalid_citations = [item for item in cited_ids if item not in evidence_ids]
    issues: list[dict[str, Any]] = []
    for item in invalid_citations:
        issues.append(_issue("INVALID_CITATION", f"Invalid evidence citation: {item}"))

    unsupported_claims = list(result.unsupported_claims)
    unsupported_claims.extend(_unsupported_marker_claims(result.answer_text, context))
    if result.answer_text and not cited_ids and "当前证据不足" not in result.answer_text:
        unsupported_claims.append("Answer contains conclusions without evidence citations.")
    if context.graph_paths and not _graph_path_used(result, context):
        issues.append(
            _issue(
                "GRAPH_PATH_AVAILABLE_NOT_USED",
                "Graph path evidence was available but not used by the answer.",
                severity="INFO",
            )
        )

    candidate_as_confirmed = _candidate_as_confirmed_count(result.answer_text)
    info_only_as_fact = _info_only_as_fact_count(result.answer_text)
    unsupported_count = len(unsupported_claims)
    for claim in unsupported_claims:
        issues.append(_issue("UNSUPPORTED_CLAIM", claim))
    if candidate_as_confirmed:
        issues.append(_issue("CANDIDATE_AS_CONFIRMED", "Candidate was phrased as confirmed."))
    if info_only_as_fact:
        issues.append(_issue("INFO_ONLY_AS_FACT", "InfoOnly item was phrased as fact."))

    grounding_passed = (
        not invalid_citations
        and unsupported_count == 0
        and candidate_as_confirmed == 0
        and info_only_as_fact == 0
    )
    return AnswerGroundingEvaluation(
        evidence_citation_count=len([item for item in cited_ids if item in evidence_ids]),
        invalid_citation_count=len(invalid_citations),
        unsupported_claim_count=unsupported_count,
        unsupported_claim_ratio=_ratio(max(len(result.answer_text.split()), 1), unsupported_count),
        graph_path_used=_graph_path_used(result, context),
        candidate_as_confirmed_count=candidate_as_confirmed,
        info_only_as_fact_count=info_only_as_fact,
        grounding_passed=grounding_passed,
        issues=issues,
    )


def compare_text_vs_graph_answers(
    text_answer: AnswerGenerationResult,
    graph_answer: AnswerGenerationResult,
    query: GraphRetrievalQuery,
) -> AnswerComparisonMetrics:
    text_entity_coverage = _answer_term_coverage(text_answer.answer_text, query.expected_entities)
    graph_entity_coverage = _answer_term_coverage(graph_answer.answer_text, query.expected_entities)
    text_relation_coverage = _answer_term_coverage(text_answer.answer_text, query.expected_relations)
    graph_relation_coverage = _answer_term_coverage(graph_answer.answer_text, query.expected_relations)
    text_citations = len(set(text_answer.cited_evidence_ids))
    graph_citations = len(set(graph_answer.cited_evidence_ids))
    text_unsupported = len(text_answer.unsupported_claims)
    graph_unsupported = len(graph_answer.unsupported_claims)
    graph_path_delta = int(graph_answer.graph_path_used) - int(text_answer.graph_path_used)
    completeness_delta = (
        (graph_entity_coverage + graph_relation_coverage)
        - (text_entity_coverage + text_relation_coverage)
    ) / 2
    evidence_delta = graph_citations - text_citations
    unsupported_delta = graph_unsupported - text_unsupported
    entity_delta = graph_entity_coverage - text_entity_coverage
    relation_delta = graph_relation_coverage - text_relation_coverage
    hallucination_delta = _hallucination_risk(graph_answer) - _hallucination_risk(text_answer)
    label, reasons = _answer_improvement_label(
        query,
        graph_answer=graph_answer,
        answer_completeness_delta=completeness_delta,
        evidence_citation_delta=evidence_delta,
        unsupported_claim_delta=unsupported_delta,
        graph_path_usage_delta=graph_path_delta,
        expected_entity_coverage_delta=entity_delta,
        expected_relation_coverage_delta=relation_delta,
        hallucination_risk_delta=hallucination_delta,
    )
    return AnswerComparisonMetrics(
        query_id=query.query_id,
        text_only_score=_answer_score(text_entity_coverage, text_relation_coverage, text_citations, text_unsupported),
        graph_aware_score=_answer_score(graph_entity_coverage, graph_relation_coverage, graph_citations, graph_unsupported),
        answer_completeness_delta=completeness_delta,
        evidence_citation_delta=evidence_delta,
        unsupported_claim_delta=unsupported_delta,
        graph_path_usage_delta=graph_path_delta,
        expected_entity_coverage_delta=entity_delta,
        expected_relation_coverage_delta=relation_delta,
        hallucination_risk_delta=hallucination_delta,
        improvement_label=label,
        reasons=reasons,
    )


def build_graph_answer_evaluation_report(
    retrieval_report: GraphRetrievalEvaluationReport,
    *,
    source: str,
    max_queries: int = 5,
) -> GraphAnswerEvaluationReport:
    text_contexts, graph_contexts = build_answer_contexts_from_retrieval_results(
        retrieval_report,
        max_queries=max_queries,
    )
    comparison_results: list[AnswerComparisonMetrics] = []
    risks: list[str] = []
    for text_context, graph_context in zip(text_contexts, graph_contexts, strict=True):
        query = _query_from_context(graph_context)
        text_answer = _grounded_result(
            generate_answer_deterministic(text_context),
            text_context,
        )
        graph_answer = _grounded_result(
            generate_answer_deterministic(graph_context),
            graph_context,
        )
        metrics = compare_text_vs_graph_answers(text_answer, graph_answer, query)
        comparison_results.append(metrics)
        if metrics.improvement_label == DEGRADED:
            risks.append(f"Answer comparison degraded for {metrics.query_id}.")

    labels = [item.improvement_label for item in comparison_results]
    return GraphAnswerEvaluationReport(
        source=source,
        query_count=len(comparison_results),
        improved_count=labels.count(IMPROVED),
        same_count=labels.count(SAME),
        degraded_count=labels.count(DEGRADED),
        inconclusive_count=labels.count(INCONCLUSIVE),
        avg_answer_completeness_delta=_avg(
            item.answer_completeness_delta for item in comparison_results
        ),
        avg_evidence_citation_delta=_avg(
            item.evidence_citation_delta for item in comparison_results
        ),
        avg_unsupported_claim_delta=_avg(
            item.unsupported_claim_delta for item in comparison_results
        ),
        avg_graph_path_usage_delta=_avg(
            item.graph_path_usage_delta for item in comparison_results
        ),
        avg_expected_entity_coverage_delta=_avg(
            item.expected_entity_coverage_delta for item in comparison_results
        ),
        avg_expected_relation_coverage_delta=_avg(
            item.expected_relation_coverage_delta for item in comparison_results
        ),
        recommended_next_step=_recommended_next_step(labels, risks),
        risks=risks,
        comparison_results=comparison_results,
    )


def build_lc_mini_graph_answer_evaluation_report(
    *,
    max_queries: int = 5,
) -> GraphAnswerEvaluationReport:
    retrieval_report = build_lc_mini_graph_retrieval_evaluation_report(
        max_queries=max_queries,
    )
    return build_graph_answer_evaluation_report(
        retrieval_report,
        source=LC_SOURCE_NAME,
        max_queries=max_queries,
    )


def build_fx_mini_graph_answer_evaluation_report(
    *,
    max_queries: int = 5,
) -> GraphAnswerEvaluationReport:
    retrieval_report = build_fx_mini_graph_retrieval_evaluation_report(
        max_queries=max_queries,
    )
    return build_graph_answer_evaluation_report(
        retrieval_report,
        source="FX_THREE_US_FULL",
        max_queries=max_queries,
    )


def serialize_graph_answer_evaluation_report(
    report: GraphAnswerEvaluationReport,
) -> dict[str, Any]:
    return asdict(report)


def get_graph_answer_runtime_flags() -> dict[str, bool]:
    return dict(_RUNTIME_FLAGS)


def _context_from_result(
    comparison: RetrievalComparisonResult,
    hits: list[RetrievalHit],
    *,
    mode: str,
) -> GraphAnswerContext:
    valid_hits: list[RetrievalHit] = []
    issues: list[dict[str, Any]] = []
    for hit in hits:
        if hit.hit_type != HIT_TEXT and not (hit.evidence_text and hit.text_hash):
            issues.append(
                _issue(
                    "GRAPH_HIT_EXCLUDED_MISSING_EVIDENCE",
                    "Graph hit missing evidence was excluded from answer context.",
                    severity="WARN",
                )
            )
            continue
        valid_hits.append(hit)

    text_hits = [hit for hit in valid_hits if hit.hit_type == HIT_TEXT]
    node_hits = [hit for hit in valid_hits if hit.hit_type == HIT_NODE]
    edge_hits = [hit for hit in valid_hits if hit.hit_type == HIT_EDGE]
    path_hits = [hit for hit in valid_hits if hit.hit_type == HIT_PATH]
    evidence_items = _evidence_items_from_hits(valid_hits, mode=mode)
    graph_paths = _graph_path_evidence_from_hits(path_hits)
    expected_entities = list(comparison.graph_aware_result.expected_entities)
    expected_relations = list(comparison.graph_aware_result.expected_relations)
    expected_keywords = list(comparison.graph_aware_result.expected_evidence_keywords)
    for item in evidence_items:
        if not (item.source_us_id and item.text_unit_id and item.text_hash):
            issues.append(
                _issue(
                    "ANSWER_CONTEXT_EVIDENCE_METADATA_INCOMPLETE",
                    f"Evidence metadata is incomplete: {item.evidence_id}",
                    severity="WARN",
                )
            )
    return GraphAnswerContext(
        query_id=comparison.query_id,
        query_text=comparison.graph_aware_result.query_text,
        mode=mode,
        text_hits=text_hits,
        node_hits=node_hits if mode == MODE_GRAPH_AWARE else [],
        edge_hits=edge_hits if mode == MODE_GRAPH_AWARE else [],
        path_hits=path_hits if mode == MODE_GRAPH_AWARE else [],
        evidence_items=evidence_items,
        graph_paths=graph_paths if mode == MODE_GRAPH_AWARE else [],
        expected_entities=expected_entities,
        expected_relations=expected_relations,
        expected_evidence_keywords=expected_keywords,
        guardrails={
            "candidate_only": True,
            "no_confirmed_claims": True,
            "no_info_only_as_fact": True,
            "use_evidence_ids": True,
        },
        issues=issues,
    )


def _evidence_items_from_hits(
    hits: list[RetrievalHit],
    *,
    mode: str,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    seen: set[tuple[str | None, str | None, str | None, str]] = set()
    for index, hit in enumerate(hits, start=1):
        if not hit.evidence_text:
            continue
        key = (hit.source_id, hit.text_hash, hit.relation_type, hit.hit_type)
        if key in seen:
            continue
        seen.add(key)
        evidence_id = f"EV-{mode}-{index:02d}"
        items.append(
            EvidenceItem(
                evidence_id=evidence_id,
                source_us_id=hit.source_us_id,
                text_unit_id=hit.text_unit_id,
                source_span=hit.source_span,
                text_hash=hit.text_hash,
                evidence_text=hit.evidence_text,
                feature_key=hit.feature_key,
                domain_code=hit.domain_code,
                section_type=hit.section_type,
                linked_entity=hit.entity_name,
                linked_relation=hit.relation_type,
                from_graph=hit.hit_type != HIT_TEXT,
            )
        )
    return items


def _graph_path_evidence_from_hits(
    path_hits: list[RetrievalHit],
) -> list[GraphPathEvidence]:
    values: list[GraphPathEvidence] = []
    for index, hit in enumerate(path_hits, start=1):
        path = hit.path or []
        nodes: list[str] = []
        for edge in path:
            _append_unique(nodes, str(edge.get("src_id") or ""))
            _append_unique(nodes, str(edge.get("tgt_id") or ""))
        values.append(
            GraphPathEvidence(
                path_id=f"PATH-{index:02d}",
                nodes=[node for node in nodes if node],
                edges=[dict(edge) for edge in path],
                relation_sequence=[
                    str(edge.get("relation_type"))
                    for edge in path
                    if edge.get("relation_type")
                ],
                source_us_ids=[hit.source_us_id] if hit.source_us_id else [],
                evidence_texts=[hit.evidence_text] if hit.evidence_text else [],
                source_spans=[hit.source_span] if hit.source_span else [],
                confidence_score=max(hit.score, 0.1),
            )
        )
    return values


def _select_cited_evidence(context: GraphAnswerContext) -> list[EvidenceItem]:
    if context.mode == MODE_TEXT_ONLY:
        return context.evidence_items[:3]
    graph_items = [item for item in context.evidence_items if item.from_graph]
    text_items = [item for item in context.evidence_items if not item.from_graph]
    return [*graph_items[:4], *text_items[:2]][:6]


def _deterministic_answer_text(
    context: GraphAnswerContext,
    *,
    cited_evidence: list[EvidenceItem],
    cited_graph_paths: list[str],
    entity_coverage: set[str],
    relation_coverage: set[str],
) -> str:
    evidence_refs = ", ".join(item.evidence_id for item in cited_evidence) or "无"
    entity_text = "、".join(sorted(entity_coverage)) or "当前证据不足"
    relation_text = "、".join(sorted(relation_coverage)) or "当前证据不足"
    lines = [
        f"结论：基于给定证据，相关实体包括 {entity_text}；关系包括 {relation_text}。证据：{evidence_refs}。",
        "证据：",
        *[
            (
                f"- {item.evidence_id}: sourceUsId={item.source_us_id}, "
                f"textUnitId={item.text_unit_id}, textHash={item.text_hash}"
            )
            for item in cited_evidence
        ],
    ]
    if context.mode == MODE_GRAPH_AWARE and cited_graph_paths:
        lines.append("影响路径：")
        for path in context.graph_paths:
            lines.append(
                f"- {path.path_id}: {' -> '.join(path.nodes)} "
                f"({', '.join(path.relation_sequence)})"
            )
    else:
        lines.append("影响路径：text-only 模式未使用图谱路径。")
    lines.append("说明：以上均为候选级证据，不声明为正式结论。")
    return "\n".join(lines)


def _grounded_result(
    result: AnswerGenerationResult,
    context: GraphAnswerContext,
) -> AnswerGenerationResult:
    grounding = evaluate_answer_grounding(result, context)
    return AnswerGenerationResult(
        query_id=result.query_id,
        mode=result.mode,
        answer_text=result.answer_text,
        cited_evidence_ids=result.cited_evidence_ids,
        cited_source_us_ids=result.cited_source_us_ids,
        cited_text_unit_ids=result.cited_text_unit_ids,
        cited_graph_paths=result.cited_graph_paths,
        unsupported_claims=[
            issue["message"]
            for issue in grounding.issues
            if issue.get("code") == "UNSUPPORTED_CLAIM"
        ],
        missing_expected_items=result.missing_expected_items,
        graph_path_used=result.graph_path_used,
        generation_mode=result.generation_mode,
        issues=[*result.issues, *grounding.issues],
    )


def _query_from_context(context: GraphAnswerContext) -> GraphRetrievalQuery:
    return GraphRetrievalQuery(
        query_id=context.query_id,
        query_text=context.query_text,
        expected_entities=list(context.expected_entities),
        expected_relations=list(context.expected_relations),
        expected_evidence_keywords=list(context.expected_evidence_keywords),
    )


def _covered_terms_from_context(
    terms: list[str],
    context: GraphAnswerContext,
) -> set[str]:
    searchable = "\n".join(
        [
            context.query_text,
            *(item.evidence_text for item in context.evidence_items),
            *(
                str(getattr(hit, "entity_name", "") or "")
                for hit in [*context.node_hits, *context.edge_hits]
            ),
            *(
                str(getattr(hit, "relation_type", "") or "")
                for hit in [*context.edge_hits, *context.path_hits]
            ),
            *(" ".join(path.nodes + path.relation_sequence) for path in context.graph_paths),
        ]
    )
    return {term for term in terms if _contains(searchable, term)}


def _answer_term_coverage(answer_text: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    return len([term for term in terms if _contains(answer_text, term)]) / len(terms)


def _answer_improvement_label(
    query: GraphRetrievalQuery,
    *,
    graph_answer: AnswerGenerationResult,
    answer_completeness_delta: float,
    evidence_citation_delta: int,
    unsupported_claim_delta: int,
    graph_path_usage_delta: int,
    expected_entity_coverage_delta: float,
    expected_relation_coverage_delta: float,
    hallucination_risk_delta: float,
) -> tuple[str, list[str]]:
    if not query.expected_entities and not query.expected_relations:
        return INCONCLUSIVE, ["Query has no expected answer objects."]
    if (
        unsupported_claim_delta > 0
        or hallucination_risk_delta > 0.2
        or any(issue.get("code") == "CANDIDATE_AS_CONFIRMED" for issue in graph_answer.issues)
    ):
        return DEGRADED, ["Graph-aware answer introduced unsupported or unsafe claims."]

    reasons: list[str] = []
    if expected_entity_coverage_delta > 0:
        reasons.append("expected entity coverage improved")
    if expected_relation_coverage_delta > 0:
        reasons.append("expected relation coverage improved")
    if graph_path_usage_delta > 0:
        reasons.append("graph path used")
    if evidence_citation_delta >= 0:
        reasons.append("evidence citations maintained")
    if unsupported_claim_delta <= 0:
        reasons.append("unsupported claims did not increase")
    if answer_completeness_delta > 0:
        reasons.append("answer completeness improved")

    positive_count = sum(
        [
            expected_entity_coverage_delta > 0,
            expected_relation_coverage_delta > 0,
            graph_path_usage_delta > 0,
            evidence_citation_delta >= 0,
            unsupported_claim_delta <= 0,
            answer_completeness_delta > 0,
        ]
    )
    if positive_count >= 2 and (
        expected_relation_coverage_delta > 0
        or graph_path_usage_delta > 0
        or answer_completeness_delta > 0
    ):
        return IMPROVED, reasons
    if answer_completeness_delta == 0 and graph_path_usage_delta == 0:
        return SAME, reasons or ["No material answer difference."]
    return SAME, reasons or ["Answer difference is not material."]


def _recommended_next_step(labels: list[str], risks: list[str]) -> str:
    if risks:
        return "TUNE_GRAPH_ANSWER_GROUNDING"
    if labels and labels.count(IMPROVED) > 0 and DEGRADED not in labels:
        return "PREPARE_LC_AB_QUESTION_AB_EVAL"
    if not labels:
        return "EXPAND_RETRIEVAL_ANSWER_SMOKE_QUERIES"
    return "REVIEW_GRAPH_ANSWER_CASES"


def _answer_score(
    entity_coverage: float,
    relation_coverage: float,
    citation_count: int,
    unsupported_count: int,
) -> float:
    return entity_coverage + relation_coverage + min(citation_count, 5) * 0.1 - unsupported_count


def _hallucination_risk(result: AnswerGenerationResult) -> float:
    return min(len(result.unsupported_claims) * 0.25, 1.0)


def _graph_path_used(
    result: AnswerGenerationResult,
    context: GraphAnswerContext,
) -> bool:
    if result.graph_path_used or result.cited_graph_paths:
        return True
    return any(path.path_id in result.answer_text for path in context.graph_paths)


def _source_us_ids_for_citations(
    evidence_ids: list[str],
    context: GraphAnswerContext,
) -> list[str]:
    by_id = {item.evidence_id: item for item in context.evidence_items}
    return _unique(
        [
            by_id[item].source_us_id
            for item in evidence_ids
            if item in by_id and by_id[item].source_us_id
        ]
    )


def _text_unit_ids_for_citations(
    evidence_ids: list[str],
    context: GraphAnswerContext,
) -> list[str]:
    by_id = {item.evidence_id: item for item in context.evidence_items}
    return _unique(
        [
            by_id[item].text_unit_id
            for item in evidence_ids
            if item in by_id and by_id[item].text_unit_id
        ]
    )


def _extract_evidence_ids(answer_text: str) -> list[str]:
    return _unique(re.findall(r"EV-[A-Za-z0-9_-]+-\d{2}", answer_text))


def _extract_path_ids(answer_text: str) -> list[str]:
    return _unique(re.findall(r"PATH-\d{2}", answer_text))


def _unsupported_marker_claims(
    answer_text: str,
    context: GraphAnswerContext,
) -> list[str]:
    markers = re.findall(
        r"\b(?:Nonexistent|Imaginary|Unknown)[A-Za-z0-9_]*\b|不存在实体|无证据实体",
        answer_text,
    )
    allowed_text = "\n".join(
        [
            context.query_text,
            *(context.expected_entities),
            *(context.expected_relations),
            *(item.evidence_text for item in context.evidence_items),
        ]
    )
    return [
        f"Answer mentions unsupported item: {marker}"
        for marker in markers
        if marker and marker not in allowed_text
    ]


def _candidate_as_confirmed_count(answer_text: str) -> int:
    return len(re.findall(r"Confirmed|已确认|正式事实", answer_text))


def _info_only_as_fact_count(answer_text: str) -> int:
    return len(re.findall(r"InfoOnly\s*事实|信息项为事实", answer_text))


def _issue(code: str, message: str, *, severity: str = "ERROR") -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message}


def _ratio(total: int, count: int) -> float:
    if total == 0:
        return 0.0
    return count / total


def _avg(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _contains(text: str, value: str) -> bool:
    return bool(value) and value.lower() in text.lower()


__all__ = [
    "LIVE_ANSWER_ENV",
    "build_answer_contexts_from_retrieval_results",
    "build_fx_mini_graph_answer_evaluation_report",
    "build_graph_answer_evaluation_report",
    "build_lc_mini_graph_answer_evaluation_report",
    "compare_text_vs_graph_answers",
    "evaluate_answer_grounding",
    "generate_answer_deterministic",
    "generate_answer_with_llm",
    "get_graph_answer_runtime_flags",
    "serialize_graph_answer_evaluation_report",
]
