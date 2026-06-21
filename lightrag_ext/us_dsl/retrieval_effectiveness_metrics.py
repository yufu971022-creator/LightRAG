from __future__ import annotations

from collections import defaultdict

from .multi_module_eval_types import CaseRetrievalResult, EffectivenessMetrics, EvaluationCase, RetrievalHit


def compute_effectiveness_metrics(
    cases: list[EvaluationCase],
    results: list[CaseRetrievalResult],
    *,
    k: int = 8,
) -> EffectivenessMetrics:
    case_by_id = {case.case_id: case for case in cases}
    result_by_case = {result.case_id: result for result in results}
    if not case_by_id:
        return _empty_metrics()
    recall_values: list[float] = []
    precision_values: list[float] = []
    entity_values: list[float] = []
    relation_values: list[float] = []
    dimension_values: list[float] = []
    path_values: list[float] = []
    span_values: list[float] = []
    alias_values: list[float] = []
    fallback_values: list[float] = []
    for case_id, case in case_by_id.items():
        hits = result_by_case.get(case_id, CaseRetrievalResult(case_id, case.module_code, "candidate", [])).hits[:k]
        recall_values.append(_set_recall(case.gold_text_unit_ids, [hit.text_unit_id for hit in hits]))
        precision_values.append(_precision(case, hits))
        entity_values.append(_set_recall(case.gold_semantic_object_ids, [hit.semantic_object_id for hit in hits]))
        relation_values.append(_set_recall(case.gold_relation_types, [hit.relation_type for hit in hits]))
        dimension_values.append(_set_recall(case.gold_required_dimensions, _flatten(hit.required_dimensions for hit in hits)))
        path_values.append(1.0 if any(hit.graph_path_id for hit in hits) and (case.gold_relation_types or case.gold_required_dimensions) else 0.0)
        span_values.append(_span_match(case, hits))
        alias_values.append(_keyword_recall(case.gold_evidence_keywords, hits))
        fallback_values.append(1.0 if not hits and case.task_type == "DESIGN_CONTEXT" else 1.0 if hits else 0.0)
    return EffectivenessMetrics(
        evidence_recall_at_k=_mean(recall_values),
        evidence_precision_at_k=_mean(precision_values),
        entity_recall_at_k=_mean(entity_values),
        relation_recall_at_k=_mean(relation_values),
        required_dimension_coverage=_mean(dimension_values),
        graph_path_coverage=_mean(path_values),
        source_span_match_rate=_mean(span_values),
        cross_language_alias_recall=_mean(alias_values),
        text_only_fallback_success_rate=_mean(fallback_values),
    )


def compute_per_module_effectiveness(
    cases: list[EvaluationCase],
    results: list[CaseRetrievalResult],
    *,
    k: int = 8,
) -> dict[str, EffectivenessMetrics]:
    cases_by_module: dict[str, list[EvaluationCase]] = defaultdict(list)
    results_by_module: dict[str, list[CaseRetrievalResult]] = defaultdict(list)
    for case in cases:
        cases_by_module[case.module_code].append(case)
    for result in results:
        results_by_module[result.module_code].append(result)
    return {
        module_code: compute_effectiveness_metrics(module_cases, results_by_module.get(module_code, []), k=k)
        for module_code, module_cases in cases_by_module.items()
    }


def _set_recall(gold: list[str], observed: list[str | None]) -> float:
    gold_set = {item for item in gold if item}
    if not gold_set:
        return 1.0
    observed_set = {item for item in observed if item}
    return len(gold_set & observed_set) / len(gold_set)


def _precision(case: EvaluationCase, hits: list[RetrievalHit]) -> float:
    if not hits:
        return 0.0
    gold_units = set(case.gold_text_unit_ids)
    gold_refs = set(case.gold_source_refs)
    matched = 0
    for hit in hits:
        if hit.text_unit_id in gold_units or hit.source_ref in gold_refs:
            matched += 1
    return matched / len(hits)


def _span_match(case: EvaluationCase, hits: list[RetrievalHit]) -> float:
    if not case.gold_text_unit_ids:
        return 1.0
    return 1.0 if any(hit.text_unit_id in case.gold_text_unit_ids and hit.source_span for hit in hits) else 0.0


def _keyword_recall(keywords: list[str], hits: list[RetrievalHit]) -> float:
    gold = {item.casefold() for item in keywords if item}
    if not gold:
        return 1.0
    observed = {keyword.casefold() for hit in hits for keyword in hit.evidence_keywords}
    return len(gold & observed) / len(gold)


def _flatten(values: object) -> list[str]:
    flattened: list[str] = []
    for value in values:  # type: ignore[assignment]
        flattened.extend([item for item in value if item])
    return flattened


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _empty_metrics() -> EffectivenessMetrics:
    return EffectivenessMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
