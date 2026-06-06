from __future__ import annotations

from .graph_answer_types import GraphAnswerContext
from .impact_analysis_types import (
    DEGRADED,
    FAIL,
    IMPROVED,
    INCONCLUSIVE,
    PASS,
    SAME,
    WARN,
    ImpactAnalysisCase,
    ImpactAnalysisComparisonResult,
    ImpactAnalysisJudgement,
    ImpactAnalysisResult,
)


def judge_impact_analysis(
    case: ImpactAnalysisCase,
    result: ImpactAnalysisResult,
    context: GraphAnswerContext,
) -> ImpactAnalysisJudgement:
    evidence_ids = {item.evidence_id for item in context.evidence_items}
    invalid_citations = [item for item in result.cited_evidence_ids if item not in evidence_ids]
    covered_entities = [
        item for item in case.expected_entities if _contains_many(item, result.impacted_entities, result.analysis_markdown)
    ]
    covered_relations = [
        item for item in case.expected_relations if _contains_many(item, result.impacted_relations, result.analysis_markdown)
    ]
    missing_entities = [item for item in case.expected_entities if item not in covered_entities]
    missing_relations = [item for item in case.expected_relations if item not in covered_relations]
    missing_dimensions = [
        item
        for item in case.expected_impact_dimensions
        if not _contains_many(item, result.impacted_domains, result.analysis_markdown)
    ]
    unsupported_claims = [
        *result.unsupported_claims,
        *_unsupported_marker_claims(result.analysis_markdown, context),
    ]
    if result.analysis_markdown and not result.cited_evidence_ids and not _explicitly_uncertain(result.analysis_markdown):
        unsupported_claims.append("Impact analysis contains conclusions without evidence citations.")
    candidate_count = result.candidate_as_confirmed_count + _candidate_as_confirmed_count(result.analysis_markdown)
    info_only_count = result.info_only_as_fact_count + _info_only_as_fact_count(result.analysis_markdown)
    false_positive_claims = _false_positive_claims(case, result.analysis_markdown)

    impact_score = _coverage_score(
        len(case.expected_entities) + len(case.expected_domains) + len(case.expected_impact_dimensions),
        len(covered_entities)
        + len([item for item in case.expected_domains if _contains_many(item, result.impacted_domains, result.analysis_markdown)])
        + len(case.expected_impact_dimensions)
        - len(missing_dimensions),
    )
    relation_score = _coverage_score(len(case.expected_relations), len(covered_relations))
    if result.graph_path_used and relation_score < 5:
        relation_score = min(5, relation_score + 1)
    evidence_score = _evidence_score(
        len([item for item in result.cited_evidence_ids if item in evidence_ids]),
        len(invalid_citations),
    )
    source_span_score = _source_span_score(result, context)
    risk_score = _risk_score(
        len(unsupported_claims),
        len(false_positive_claims),
        candidate_count,
        info_only_count,
    )
    review_score = _review_readiness_score(result, missing_entities, missing_relations, unsupported_claims)
    score = round(
        (
            impact_score
            + relation_score
            + evidence_score
            + source_span_score
            + risk_score
            + review_score
        )
        / 30
        * 100
    )
    label = _result_label(
        score,
        unsupported_claim_count=len(unsupported_claims),
        invalid_citation_count=len(invalid_citations),
        candidate_as_confirmed_count=candidate_count,
    )
    return ImpactAnalysisJudgement(
        case_id=case.case_id,
        mode=result.mode,
        score=score,
        result=label,
        impact_completeness_score=impact_score,
        relation_path_score=relation_score,
        evidence_grounding_score=evidence_score,
        source_span_score=source_span_score,
        risk_control_score=risk_score,
        review_readiness_score=review_score,
        unsupported_claim_count=len(unsupported_claims),
        invalid_citation_count=len(invalid_citations),
        missing_expected_dimensions=missing_dimensions,
        missing_expected_entities=missing_entities,
        missing_expected_relations=missing_relations,
        covered_expected_entities=covered_entities,
        covered_expected_relations=covered_relations,
        false_positive_claims=false_positive_claims,
        candidate_as_confirmed_count=candidate_count,
        info_only_as_fact_count=info_only_count,
        reasons=_reasons(
            missing_entities=missing_entities,
            missing_relations=missing_relations,
            missing_dimensions=missing_dimensions,
            unsupported_claims=unsupported_claims,
            invalid_citations=invalid_citations,
        ),
    )


def compare_impact_analysis_results(
    *,
    case: ImpactAnalysisCase,
    text_judgement: ImpactAnalysisJudgement,
    graph_judgement: ImpactAnalysisJudgement,
    graph_path_used: bool,
    graph_missing_expected_objects: list[str] | None = None,
) -> ImpactAnalysisComparisonResult:
    missing_graph = graph_missing_expected_objects or []
    score_delta = graph_judgement.score - text_judgement.score
    completeness_delta = graph_judgement.impact_completeness_score - text_judgement.impact_completeness_score
    relation_delta = graph_judgement.relation_path_score - text_judgement.relation_path_score
    evidence_delta = graph_judgement.evidence_grounding_score - text_judgement.evidence_grounding_score
    source_span_delta = graph_judgement.source_span_score - text_judgement.source_span_score
    unsupported_delta = graph_judgement.unsupported_claim_count - text_judgement.unsupported_claim_count
    label, reasons = _comparison_label(
        case=case,
        graph_judgement=graph_judgement,
        text_judgement=text_judgement,
        graph_path_used=graph_path_used,
        missing_graph=missing_graph,
        score_delta=score_delta,
        completeness_delta=completeness_delta,
        relation_delta=relation_delta,
        evidence_delta=evidence_delta,
    )
    return ImpactAnalysisComparisonResult(
        case_id=case.case_id,
        text_only_judgement=text_judgement,
        graph_aware_judgement=graph_judgement,
        score_delta=score_delta,
        impact_completeness_delta=completeness_delta,
        relation_path_delta=relation_delta,
        evidence_grounding_delta=evidence_delta,
        source_span_delta=source_span_delta,
        unsupported_claim_delta=unsupported_delta,
        improvement_label=label,
        reasons=reasons,
    )


def _comparison_label(
    *,
    case: ImpactAnalysisCase,
    graph_judgement: ImpactAnalysisJudgement,
    text_judgement: ImpactAnalysisJudgement,
    graph_path_used: bool,
    missing_graph: list[str],
    score_delta: int,
    completeness_delta: int,
    relation_delta: int,
    evidence_delta: int,
) -> tuple[str, list[str]]:
    if (
        graph_judgement.unsupported_claim_count > text_judgement.unsupported_claim_count
        or graph_judgement.invalid_citation_count > text_judgement.invalid_citation_count
        or graph_judgement.candidate_as_confirmed_count
        or graph_judgement.info_only_as_fact_count
        or graph_judgement.false_positive_claims
    ):
        return DEGRADED, ["Graph-aware impact analysis introduced unsafe grounding issue."]
    if missing_graph and case.graph_coverage_expectation == "partial" and score_delta <= 5:
        return INCONCLUSIVE, ["Case is outside current graph subset coverage."]
    improvement_signals = [
        score_delta > 5,
        completeness_delta > 0,
        relation_delta > 0,
        evidence_delta >= 0 and graph_path_used,
    ]
    if sum(improvement_signals) >= 2:
        return IMPROVED, ["Graph-aware impact analysis improved scope, relations, or paths."]
    if abs(score_delta) <= 5:
        return SAME, ["Score difference is not material."]
    return DEGRADED, ["Graph-aware impact analysis score is materially lower."]


def _coverage_score(total: int, covered: int) -> int:
    if total <= 0:
        return 5
    ratio = covered / total
    if ratio >= 0.9:
        return 5
    if ratio >= 0.7:
        return 4
    if ratio >= 0.4:
        return 3
    if ratio > 0:
        return 2
    return 1


def _evidence_score(valid_citation_count: int, invalid_citation_count: int) -> int:
    if invalid_citation_count:
        return 0
    if valid_citation_count >= 3:
        return 5
    if valid_citation_count >= 1:
        return 4
    return 1


def _source_span_score(result: ImpactAnalysisResult, context: GraphAnswerContext) -> int:
    evidence_by_id = {item.evidence_id: item for item in context.evidence_items}
    cited = [evidence_by_id[item] for item in result.cited_evidence_ids if item in evidence_by_id]
    if not cited:
        return 1
    complete = [
        item for item in cited if item.source_span and item.text_hash and item.text_unit_id and item.source_us_id
    ]
    return _coverage_score(len(cited), len(complete))


def _risk_score(
    unsupported_claim_count: int,
    false_positive_count: int,
    candidate_as_confirmed_count: int,
    info_only_as_fact_count: int,
) -> int:
    if candidate_as_confirmed_count or info_only_as_fact_count:
        return 0
    if unsupported_claim_count or false_positive_count:
        return 2
    return 5


def _review_readiness_score(
    result: ImpactAnalysisResult,
    missing_entities: list[str],
    missing_relations: list[str],
    unsupported_claims: list[str],
) -> int:
    if unsupported_claims:
        return 2
    if not missing_entities and not missing_relations and result.cited_evidence_ids:
        return 5
    if result.cited_evidence_ids:
        return 4
    return 2


def _result_label(
    score: int,
    *,
    unsupported_claim_count: int,
    invalid_citation_count: int,
    candidate_as_confirmed_count: int,
) -> str:
    if invalid_citation_count or candidate_as_confirmed_count:
        return FAIL
    if score >= 85 and unsupported_claim_count == 0:
        return PASS
    if score >= 65 and unsupported_claim_count <= 1:
        return WARN
    return FAIL


def _false_positive_claims(case: ImpactAnalysisCase, text: str) -> list[str]:
    return [claim for claim in case.forbidden_claims if claim and claim in text]


def _unsupported_marker_claims(text: str, context: GraphAnswerContext) -> list[str]:
    supported = {
        *context.expected_entities,
        *context.expected_relations,
        *(item.linked_entity for item in context.evidence_items if item.linked_entity),
        *(item.linked_relation for item in context.evidence_items if item.linked_relation),
    }
    claims: list[str] = []
    for marker in ("NonexistentEntity", "NoSuchRelation"):
        if marker in text and marker not in supported:
            claims.append(f"Unsupported claim outside context: {marker}")
    return claims


def _candidate_as_confirmed_count(text: str) -> int:
    lowered = text.lower()
    return int("candidate" in lowered and ("confirmed" in lowered or "已确认" in text))


def _info_only_as_fact_count(text: str) -> int:
    lowered = text.lower()
    return int("infoonly" in lowered and ("fact" in lowered or "事实" in text))


def _explicitly_uncertain(text: str) -> bool:
    lowered = text.lower()
    return "to be confirmed" in lowered or "open questions" in lowered or "当前证据不足" in text


def _contains_many(term: str, values: list[str], text: str) -> bool:
    lowered = term.lower()
    return any(lowered in value.lower() for value in values) or lowered in text.lower()


def _contains(text: str, term: str) -> bool:
    return term.lower() in text.lower()


def _reasons(
    *,
    missing_entities: list[str],
    missing_relations: list[str],
    missing_dimensions: list[str],
    unsupported_claims: list[str],
    invalid_citations: list[str],
) -> list[str]:
    reasons: list[str] = []
    if missing_entities:
        reasons.append(f"Missing expected entities: {', '.join(missing_entities)}.")
    if missing_relations:
        reasons.append(f"Missing expected relations: {', '.join(missing_relations)}.")
    if missing_dimensions:
        reasons.append(f"Missing impact dimensions: {', '.join(missing_dimensions)}.")
    if unsupported_claims:
        reasons.append("Unsupported claims detected.")
    if invalid_citations:
        reasons.append("Invalid citations detected.")
    return reasons


__all__ = [
    "compare_impact_analysis_results",
    "judge_impact_analysis",
]
