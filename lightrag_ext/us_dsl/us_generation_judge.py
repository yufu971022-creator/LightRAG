from __future__ import annotations

from .graph_answer_types import GraphAnswerContext
from .us_generation_types import (
    ADOPT_ACCEPT_AS_IS,
    ADOPT_ACCEPT_MINOR,
    ADOPT_MAJOR_REVISION,
    ADOPT_REJECT,
    DEGRADED,
    EDIT_MAJOR,
    EDIT_MINOR,
    EDIT_NONE,
    EDIT_REWRITE,
    FAIL,
    IMPROVED,
    INCONCLUSIVE,
    PASS,
    SAME,
    USGenerationCase,
    USGenerationComparisonResult,
    USGenerationJudgement,
    USGenerationResult,
    WARN,
)


def judge_us_generation(
    case: USGenerationCase,
    result: USGenerationResult,
    context: GraphAnswerContext,
) -> USGenerationJudgement:
    evidence_ids = {item.evidence_id for item in context.evidence_items}
    invalid_citations = [
        item for item in result.cited_evidence_ids if item not in evidence_ids
    ]
    missing_sections = [
        section
        for section in case.expected_us_sections
        if section not in _normalized_sections(result)
    ]
    covered_points, missing_points = _expected_point_coverage(case, result, context)
    false_positive_claims = _false_positive_claims(case, result.generated_us_markdown)
    unsupported_claims = [
        *result.unsupported_claims,
        *_unsupported_marker_claims(result.generated_us_markdown, context),
    ]
    if (
        result.generated_us_markdown
        and not result.cited_evidence_ids
        and not _explicitly_uncertain(result.generated_us_markdown)
    ):
        unsupported_claims.append("Generated US contains conclusions without evidence citations.")

    candidate_count = result.candidate_as_confirmed_count + _candidate_as_confirmed_count(
        result.generated_us_markdown
    )
    info_only_count = result.info_only_as_fact_count + _info_only_as_fact_count(
        result.generated_us_markdown
    )
    structure_score = _coverage_score(
        len(case.expected_us_sections),
        len(case.expected_us_sections) - len(missing_sections),
    )
    business_score = _coverage_score(
        len([*case.expected_entities, *case.expected_relations, *case.expected_evidence_keywords]),
        _expected_item_coverage(case, result.generated_us_markdown, context),
    )
    evidence_score = _evidence_score(
        len([item for item in result.cited_evidence_ids if item in evidence_ids]),
        len(invalid_citations),
    )
    source_span_score = _source_span_score(result, context)
    consistency_score = _consistency_score(
        len(unsupported_claims),
        len(false_positive_claims),
        candidate_count,
        info_only_count,
    )
    version_score = _version_handling_score(case, result)
    dfx_score = _dfx_score(case, result)
    review_score = _review_readiness_score(result, missing_sections, unsupported_claims)
    score = round(
        (
            structure_score
            + business_score
            + evidence_score
            + source_span_score
            + consistency_score
            + version_score
            + dfx_score
            + review_score
        )
        / 40
        * 100
    )
    if _version_review_still_uncertain(case, result):
        score = min(score, 84)
    if len(missing_sections) >= max(2, len(case.expected_us_sections) // 2):
        score = min(score, 80)
    result_label = _result_label(
        score,
        unsupported_claim_count=len(unsupported_claims),
        invalid_citation_count=len(invalid_citations),
        candidate_as_confirmed_count=candidate_count,
    )
    adoption_level, edit_level = _adoption(score)
    reasons = _reasons(
        missing_sections=missing_sections,
        missing_points=missing_points,
        unsupported_claims=unsupported_claims,
        invalid_citations=invalid_citations,
        false_positive_claims=false_positive_claims,
    )
    return USGenerationJudgement(
        case_id=case.case_id,
        mode=result.mode,
        score=score,
        result=result_label,
        structure_completeness_score=structure_score,
        business_rule_coverage_score=business_score,
        evidence_grounding_score=evidence_score,
        source_span_score=source_span_score,
        consistency_with_existing_knowledge_score=consistency_score,
        version_handling_score=version_score,
        dfx_coverage_score=dfx_score,
        review_readiness_score=review_score,
        unsupported_claim_count=len(unsupported_claims),
        invalid_citation_count=len(invalid_citations),
        missing_expected_sections=missing_sections,
        missing_expected_points=missing_points,
        covered_expected_points=covered_points,
        false_positive_claims=false_positive_claims,
        candidate_as_confirmed_count=candidate_count,
        info_only_as_fact_count=info_only_count,
        estimated_human_edit_level=edit_level,
        adoption_level=adoption_level,
        reasons=reasons,
    )


def compare_us_generation_results(
    *,
    case: USGenerationCase,
    text_judgement: USGenerationJudgement,
    graph_judgement: USGenerationJudgement,
    graph_path_used: bool,
    graph_missing_expected_objects: list[str] | None = None,
) -> USGenerationComparisonResult:
    score_delta = graph_judgement.score - text_judgement.score
    evidence_delta = (
        graph_judgement.evidence_grounding_score
        - text_judgement.evidence_grounding_score
    )
    source_span_delta = graph_judgement.source_span_score - text_judgement.source_span_score
    unsupported_delta = (
        graph_judgement.unsupported_claim_count
        - text_judgement.unsupported_claim_count
    )
    structure_delta = (
        graph_judgement.structure_completeness_score
        - text_judgement.structure_completeness_score
    )
    business_delta = (
        graph_judgement.business_rule_coverage_score
        - text_judgement.business_rule_coverage_score
    )
    review_delta = (
        graph_judgement.review_readiness_score - text_judgement.review_readiness_score
    )
    adoption_delta = _adoption_rank(graph_judgement.adoption_level) - _adoption_rank(
        text_judgement.adoption_level
    )
    label, reasons = _comparison_label(
        case=case,
        graph_judgement=graph_judgement,
        text_judgement=text_judgement,
        graph_path_used=graph_path_used,
        graph_missing_expected_objects=graph_missing_expected_objects or [],
        score_delta=score_delta,
        evidence_delta=evidence_delta,
        structure_delta=structure_delta,
        business_delta=business_delta,
        review_delta=review_delta,
        adoption_delta=adoption_delta,
    )
    return USGenerationComparisonResult(
        case_id=case.case_id,
        text_only_judgement=text_judgement,
        graph_aware_judgement=graph_judgement,
        score_delta=score_delta,
        evidence_grounding_delta=evidence_delta,
        source_span_delta=source_span_delta,
        unsupported_claim_delta=unsupported_delta,
        structure_completeness_delta=structure_delta,
        business_rule_coverage_delta=business_delta,
        review_readiness_delta=review_delta,
        adoption_level_delta=adoption_delta,
        improvement_label=label,
        reasons=reasons,
    )


def _comparison_label(
    *,
    case: USGenerationCase,
    graph_judgement: USGenerationJudgement,
    text_judgement: USGenerationJudgement,
    graph_path_used: bool,
    graph_missing_expected_objects: list[str],
    score_delta: int,
    evidence_delta: int,
    structure_delta: int,
    business_delta: int,
    review_delta: int,
    adoption_delta: int,
) -> tuple[str, list[str]]:
    if (
        graph_judgement.unsupported_claim_count > text_judgement.unsupported_claim_count
        or graph_judgement.invalid_citation_count > text_judgement.invalid_citation_count
        or graph_judgement.candidate_as_confirmed_count
        or graph_judgement.info_only_as_fact_count
        or graph_judgement.false_positive_claims
    ):
        return DEGRADED, ["Graph-aware generation introduced unsafe grounding issue."]
    if graph_missing_expected_objects and case.graph_coverage_expectation == "partial":
        return INCONCLUSIVE, ["Case is outside current graph subset coverage."]
    if score_delta > 5:
        return IMPROVED, ["Graph-aware US score improved by more than 5."]
    improvement_signals = [
        structure_delta > 0,
        business_delta > 0,
        evidence_delta >= 0 and graph_path_used,
        review_delta > 0,
        adoption_delta > 0,
    ]
    if sum(improvement_signals) >= 2 and score_delta >= 0:
        return IMPROVED, ["Graph-aware US improved structure, evidence, or review readiness."]
    if abs(score_delta) <= 5:
        return SAME, ["Score difference is not material."]
    return DEGRADED, ["Graph-aware US score is materially lower."]


def _normalized_sections(result: USGenerationResult) -> set[str]:
    return {section.lower().strip() for section in result.generated_sections}


def _expected_point_coverage(
    case: USGenerationCase,
    result: USGenerationResult,
    context: GraphAnswerContext,
) -> tuple[list[str], list[str]]:
    searchable = "\n".join(
        [
            result.generated_us_markdown,
            *(item.evidence_text for item in context.evidence_items),
            *context.expected_entities,
            *context.expected_relations,
            *context.expected_evidence_keywords,
        ]
    )
    expected_points = [
        *case.expected_entities,
        *case.expected_relations,
        *case.expected_evidence_keywords,
        *case.expected_domains,
    ]
    covered = [item for item in expected_points if _contains(searchable, item)]
    missing = [item for item in expected_points if item not in covered]
    return covered, missing


def _expected_item_coverage(
    case: USGenerationCase,
    markdown: str,
    context: GraphAnswerContext,
) -> int:
    searchable = "\n".join(
        [
            markdown,
            *(item.evidence_text for item in context.evidence_items),
        ]
    )
    items = [
        *case.expected_entities,
        *case.expected_relations,
        *case.expected_evidence_keywords,
    ]
    if not items:
        return 1
    return sum(1 for item in items if _contains(searchable, item))


def _coverage_score(total: int, covered: int) -> int:
    if total == 0:
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


def _source_span_score(result: USGenerationResult, context: GraphAnswerContext) -> int:
    evidence_by_id = {item.evidence_id: item for item in context.evidence_items}
    cited = [
        evidence_by_id[item]
        for item in result.cited_evidence_ids
        if item in evidence_by_id
    ]
    if not cited:
        return 1
    complete = [
        item
        for item in cited
        if item.source_span and item.text_hash and item.text_unit_id and item.source_us_id
    ]
    return _coverage_score(len(cited), len(complete))


def _consistency_score(
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


def _version_handling_score(case: USGenerationCase, result: USGenerationResult) -> int:
    if "VERSION_REVIEW_US" != case.generation_task_type:
        return 5
    text = result.generated_us_markdown.lower()
    if "to be confirmed" in text or "open questions" in text or "人工确认" in text:
        return 5
    return 2


def _version_review_still_uncertain(
    case: USGenerationCase,
    result: USGenerationResult,
) -> bool:
    if "VERSION_REVIEW_US" != case.generation_task_type:
        return False
    text = result.generated_us_markdown.lower()
    return (
        "to be confirmed" in text
        or "open questions" in text
        or "人工确认" in text
        or "证据不足" in text
    )


def _dfx_score(case: USGenerationCase, result: USGenerationResult) -> int:
    if "dfx" not in {section.lower() for section in case.expected_us_sections}:
        return 5
    return 5 if "dfx" in _normalized_sections(result) else 2


def _review_readiness_score(
    result: USGenerationResult,
    missing_sections: list[str],
    unsupported_claims: list[str],
) -> int:
    if unsupported_claims:
        return 2
    if not missing_sections and result.cited_evidence_ids:
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


def _adoption(score: int) -> tuple[str, str]:
    if score >= 90:
        return ADOPT_ACCEPT_AS_IS, EDIT_NONE
    if score >= 80:
        return ADOPT_ACCEPT_MINOR, EDIT_MINOR
    if score >= 65:
        return ADOPT_MAJOR_REVISION, EDIT_MAJOR
    return ADOPT_REJECT, EDIT_REWRITE


def _adoption_rank(value: str) -> int:
    return {
        ADOPT_REJECT: 0,
        ADOPT_MAJOR_REVISION: 1,
        ADOPT_ACCEPT_MINOR: 2,
        ADOPT_ACCEPT_AS_IS: 3,
    }.get(value, 0)


def _false_positive_claims(case: USGenerationCase, text: str) -> list[str]:
    return [claim for claim in case.forbidden_claims if _contains(text, claim)]


def _unsupported_marker_claims(text: str, context: GraphAnswerContext) -> list[str]:
    claims: list[str] = []
    searchable = "\n".join(
        [
            text,
            *(context.expected_entities),
            *(context.expected_relations),
            *(item.evidence_text for item in context.evidence_items),
        ]
    )
    for marker in ["NonexistentEntity", "NoSuchRelation"]:
        if marker in text and marker not in searchable.replace(text, ""):
            claims.append(f"Unsupported marker appears in generated US: {marker}")
    return claims


def _candidate_as_confirmed_count(text: str) -> int:
    lowered = text.lower()
    return int("candidate" in lowered and "confirmed" in lowered)


def _info_only_as_fact_count(text: str) -> int:
    lowered = text.lower()
    return int("info_only" in lowered and "fact" in lowered)


def _explicitly_uncertain(text: str) -> bool:
    lowered = text.lower()
    return (
        "open questions" in lowered
        or "to be confirmed" in lowered
        or "当前证据不足" in text
        or "待确认" in text
        or "人工确认" in text
    )


def _reasons(
    *,
    missing_sections: list[str],
    missing_points: list[str],
    unsupported_claims: list[str],
    invalid_citations: list[str],
    false_positive_claims: list[str],
) -> list[str]:
    reasons: list[str] = []
    if missing_sections:
        reasons.append(f"missing_sections={len(missing_sections)}")
    if missing_points:
        reasons.append(f"missing_expected_points={len(missing_points)}")
    if unsupported_claims:
        reasons.append("unsupported claim detected")
    if invalid_citations:
        reasons.append("invalid citation detected")
    if false_positive_claims:
        reasons.append("false positive claim detected")
    if not reasons:
        reasons.append("grounded US generation is review-ready")
    return reasons


def _contains(text: str, value: str) -> bool:
    return bool(value) and value.lower() in text.lower()


__all__ = [
    "compare_us_generation_results",
    "judge_us_generation",
]
