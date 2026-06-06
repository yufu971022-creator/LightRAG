from __future__ import annotations

from typing import Any

from .business_qa_types import (
    BusinessQaJudgement,
    business_case_coverage_expectation,
)
from .graph_answer_eval import evaluate_answer_grounding
from .graph_answer_types import AnswerGenerationResult, GraphAnswerContext
from .graph_retrieval_types import DEGRADED, IMPROVED, INCONCLUSIVE, SAME


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


def judge_business_qa_answer(
    case: Any,
    answer: AnswerGenerationResult,
    context: GraphAnswerContext,
) -> BusinessQaJudgement:
    grounding = evaluate_answer_grounding(answer, context)
    false_positive_claims = _false_positive_claims(case, answer.answer_text)
    covered_points, missing_points = _expected_point_coverage(case, answer.answer_text, context)
    completeness_score = _coverage_score(
        len(getattr(case, "expected_answer_points", [])),
        len(covered_points),
    )
    expected_item_coverage = _expected_item_coverage(case, answer.answer_text)
    completeness_score = max(completeness_score, _coverage_score(1, expected_item_coverage))
    evidence_score = _evidence_score(
        grounding.evidence_citation_count,
        grounding.invalid_citation_count,
    )
    source_span_score = _source_span_score(answer, context)
    business_score = _business_score(
        grounding.unsupported_claim_count,
        grounding.candidate_as_confirmed_count,
        grounding.info_only_as_fact_count,
        len(false_positive_claims),
    )
    if business_case_coverage_expectation(case) == "partial" and answer.cited_evidence_ids:
        completeness_score = max(completeness_score, 3)
        business_score = max(business_score, 3)

    score = round(
        (
            completeness_score
            + evidence_score
            + source_span_score
            + business_score
        )
        / 20
        * 100,
        2,
    )
    result = _result_label(
        score,
        grounding.unsupported_claim_count,
        grounding.invalid_citation_count,
        grounding.candidate_as_confirmed_count,
        len(false_positive_claims),
    )
    reasons = _reasons(
        covered_points=covered_points,
        missing_points=missing_points,
        grounding=grounding,
        false_positive_claims=false_positive_claims,
    )
    return BusinessQaJudgement(
        case_id=case.case_id,
        mode=answer.mode,
        score=score,
        result=result,
        answer_completeness_score=completeness_score,
        evidence_grounding_score=evidence_score,
        source_span_score=source_span_score,
        business_correctness_score=business_score,
        unsupported_claim_count=grounding.unsupported_claim_count,
        invalid_citation_count=grounding.invalid_citation_count,
        missing_expected_points=missing_points,
        covered_expected_points=covered_points,
        false_positive_claims=false_positive_claims,
        candidate_as_confirmed_count=grounding.candidate_as_confirmed_count,
        info_only_as_fact_count=grounding.info_only_as_fact_count,
        reasons=reasons,
    )


def compare_business_qa_answers(
    *,
    case: Any,
    text_judgement: BusinessQaJudgement,
    graph_judgement: BusinessQaJudgement,
    graph_path_used: bool,
    graph_missing_expected_objects: list[str] | None = None,
) -> tuple[str, list[str]]:
    missing_graph = graph_missing_expected_objects or []
    if (
        graph_judgement.unsupported_claim_count > text_judgement.unsupported_claim_count
        or graph_judgement.invalid_citation_count > text_judgement.invalid_citation_count
        or graph_judgement.candidate_as_confirmed_count
        or graph_judgement.info_only_as_fact_count
        or graph_judgement.false_positive_claims
    ):
        return DEGRADED, ["Graph-aware answer introduced unsafe grounding issue."]
    if (
        missing_graph
        and business_case_coverage_expectation(case) == "partial"
        and graph_judgement.score <= text_judgement.score + 5
    ):
        return INCONCLUSIVE, ["Case is outside the current graph subset coverage."]
    if graph_judgement.score > text_judgement.score + 5:
        return IMPROVED, ["Graph-aware score improved by more than 5."]
    if graph_path_used and graph_judgement.score >= text_judgement.score:
        return IMPROVED, ["Graph-aware answer used relation/path evidence."]
    if abs(graph_judgement.score - text_judgement.score) <= 5:
        return SAME, ["Score difference is not material."]
    return DEGRADED, ["Graph-aware score is materially lower."]


def _expected_point_coverage(
    case: Any,
    answer_text: str,
    context: GraphAnswerContext,
) -> tuple[list[str], list[str]]:
    searchable = "\n".join(
        [
            answer_text,
            *(item.evidence_text for item in context.evidence_items),
            *context.expected_entities,
            *context.expected_relations,
            *context.expected_evidence_keywords,
        ]
    )
    covered: list[str] = []
    missing: list[str] = []
    for point in getattr(case, "expected_answer_points", []):
        keywords = _point_keywords(point)
        if not keywords or any(_contains(searchable, keyword) for keyword in keywords):
            covered.append(point)
        else:
            missing.append(point)
    return covered, missing


def _expected_item_coverage(case: Any, answer_text: str) -> int:
    items = [
        *getattr(case, "expected_entities", []),
        *getattr(case, "expected_relations", []),
        *getattr(case, "expected_evidence_keywords", []),
    ]
    if not items:
        return 1
    return sum(1 for item in items if _contains(answer_text, item))


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


def _evidence_score(citation_count: int, invalid_citation_count: int) -> int:
    if invalid_citation_count:
        return 0
    if citation_count >= 3:
        return 5
    if citation_count >= 1:
        return 4
    return 1


def _source_span_score(answer: AnswerGenerationResult, context: GraphAnswerContext) -> int:
    evidence_by_id = {item.evidence_id: item for item in context.evidence_items}
    cited = [
        evidence_by_id[item]
        for item in answer.cited_evidence_ids
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


def _business_score(
    unsupported_claim_count: int,
    candidate_as_confirmed_count: int,
    info_only_as_fact_count: int,
    false_positive_count: int,
) -> int:
    if candidate_as_confirmed_count or info_only_as_fact_count:
        return 0
    if unsupported_claim_count or false_positive_count:
        return 2
    return 5


def _result_label(
    score: float,
    unsupported_claim_count: int,
    invalid_citation_count: int,
    candidate_as_confirmed_count: int,
    false_positive_count: int,
) -> str:
    if invalid_citation_count or candidate_as_confirmed_count:
        return FAIL
    if score >= 85 and unsupported_claim_count == 0 and false_positive_count == 0:
        return PASS
    if score >= 65 and unsupported_claim_count <= 1:
        return WARN
    return FAIL


def _false_positive_claims(case: Any, answer_text: str) -> list[str]:
    return [
        claim
        for claim in getattr(case, "forbidden_claims", [])
        if _contains(answer_text, claim)
    ]


def _reasons(
    *,
    covered_points: list[str],
    missing_points: list[str],
    grounding,
    false_positive_claims: list[str],
) -> list[str]:
    reasons = [f"covered_expected_points={len(covered_points)}"]
    if missing_points:
        reasons.append(f"missing_expected_points={len(missing_points)}")
    if grounding.invalid_citation_count:
        reasons.append("invalid citation detected")
    if grounding.unsupported_claim_count:
        reasons.append("unsupported claim detected")
    if false_positive_claims:
        reasons.append("false positive claim detected")
    return reasons


def _point_keywords(point: str) -> list[str]:
    words = [
        token
        for token in point.replace("/", " ").replace(" / ", " ").split()
        if len(token) >= 3
    ]
    return [
        word.strip("，。；、,.()[]`")
        for word in words
        if any(char.isascii() for char in word)
    ][:4]


def _contains(text: str, value: str) -> bool:
    return bool(value) and value.lower() in text.lower()


__all__ = [
    "FAIL",
    "PASS",
    "WARN",
    "BusinessQaJudgement",
    "compare_business_qa_answers",
    "judge_business_qa_answer",
]
