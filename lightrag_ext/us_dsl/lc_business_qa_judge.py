from __future__ import annotations

from typing import Any

from .business_qa_judge import (
    FAIL,
    PASS,
    WARN,
    compare_business_qa_answers,
    judge_business_qa_answer,
)
from .business_qa_types import BusinessQaJudgement
from .graph_answer_types import AnswerGenerationResult, GraphAnswerContext


LCBusinessQaJudgement = BusinessQaJudgement


def judge_lc_business_answer(
    case: Any,
    answer: AnswerGenerationResult,
    context: GraphAnswerContext,
) -> LCBusinessQaJudgement:
    return judge_business_qa_answer(case, answer, context)


def compare_lc_business_judgements(
    *,
    case: Any,
    text_judgement: LCBusinessQaJudgement,
    graph_judgement: LCBusinessQaJudgement,
    graph_path_used: bool,
    graph_missing_expected_objects: list[str] | None = None,
) -> tuple[str, list[str]]:
    return compare_business_qa_answers(
        case=case,
        text_judgement=text_judgement,
        graph_judgement=graph_judgement,
        graph_path_used=graph_path_used,
        graph_missing_expected_objects=graph_missing_expected_objects,
    )


__all__ = [
    "FAIL",
    "PASS",
    "WARN",
    "LCBusinessQaJudgement",
    "compare_lc_business_judgements",
    "judge_lc_business_answer",
]
