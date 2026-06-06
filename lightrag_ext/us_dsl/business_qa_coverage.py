from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .business_qa_types import (
    BusinessQaCaseCoverage,
    BusinessQaGraphCoverageReport,
)
from .kg_payload_types import DslKgPayload


FULL = "FULL"
PARTIAL = "PARTIAL"
NONE = "NONE"


def evaluate_business_case_graph_coverage(
    cases: list[Any],
    graph_payload: DslKgPayload,
    *,
    module_name: str = "",
    case_pack_name: str = "",
    selected_chunk_count: int | None = None,
    selected_entity_count: int | None = None,
    selected_relationship_count: int | None = None,
) -> BusinessQaGraphCoverageReport:
    entity_names = {entity.entity_name for entity in graph_payload.entities}
    relation_types = {relationship.keywords for relationship in graph_payload.relationships}
    case_coverage: dict[str, str] = {}
    case_reports: list[BusinessQaCaseCoverage] = []
    missing_entities_by_case: dict[str, list[str]] = {}
    missing_relations_by_case: dict[str, list[str]] = {}
    total_entities = 0
    covered_entities_total = 0
    total_relations = 0
    covered_relations_total = 0

    for case in cases:
        expected_entities = list(getattr(case, "expected_entities", []))
        expected_relations = list(getattr(case, "expected_relations", []))
        covered_entities = [item for item in expected_entities if item in entity_names]
        missing_entities = [item for item in expected_entities if item not in entity_names]
        covered_relations = [item for item in expected_relations if item in relation_types]
        missing_relations = [item for item in expected_relations if item not in relation_types]
        coverage_status = coverage_label(
            expected_entities,
            expected_relations,
            missing_entities,
            missing_relations,
        )
        total_entities += len(expected_entities)
        covered_entities_total += len(covered_entities)
        total_relations += len(expected_relations)
        covered_relations_total += len(covered_relations)
        case_coverage[case.case_id] = coverage_status
        missing_entities_by_case[case.case_id] = missing_entities
        missing_relations_by_case[case.case_id] = missing_relations
        case_reports.append(
            BusinessQaCaseCoverage(
                case_id=case.case_id,
                level=getattr(case, "level", "L1"),
                question=getattr(case, "question", ""),
                coverage_status=coverage_status,
                covered_entities=covered_entities,
                missing_entities=missing_entities,
                covered_relations=covered_relations,
                missing_relations=missing_relations,
                graph_coverage_reason=_coverage_reason(
                    coverage_status,
                    covered_entities,
                    covered_relations,
                    missing_entities,
                    missing_relations,
                ),
            )
        )

    full_count = sum(1 for item in case_coverage.values() if item == FULL)
    partial_count = sum(1 for item in case_coverage.values() if item == PARTIAL)
    none_count = sum(1 for item in case_coverage.values() if item == NONE)
    coverage_ratio = _ratio(full_count + partial_count, len(cases))
    entity_ratio = _ratio(covered_entities_total, total_entities)
    relation_ratio = _ratio(covered_relations_total, total_relations)
    risks = _coverage_risks(none_count, len(cases))
    return BusinessQaGraphCoverageReport(
        module_name=module_name,
        case_pack_name=case_pack_name,
        case_count=len(cases),
        covered_case_count=full_count,
        partial_case_count=partial_count,
        uncovered_case_count=none_count,
        full_coverage_count=full_count,
        partial_coverage_count=partial_count,
        no_coverage_count=none_count,
        case_coverage=case_coverage,
        cases=case_reports,
        missing_entities_by_case=missing_entities_by_case,
        missing_relations_by_case=missing_relations_by_case,
        graph_entity_coverage_ratio=entity_ratio,
        graph_relation_coverage_ratio=relation_ratio,
        entity_coverage_ratio=entity_ratio,
        relation_coverage_ratio=relation_ratio,
        coverage_ratio=coverage_ratio,
        recommended_subset_limits=_recommended_subset_limits(none_count),
        selected_chunk_count=(
            len(graph_payload.chunks)
            if selected_chunk_count is None
            else selected_chunk_count
        ),
        selected_entity_count=(
            len(graph_payload.entities)
            if selected_entity_count is None
            else selected_entity_count
        ),
        selected_relationship_count=(
            len(graph_payload.relationships)
            if selected_relationship_count is None
            else selected_relationship_count
        ),
        selected_entities=sorted(entity_names),
        selected_relations=sorted(relation_types),
        risks=risks,
        recommended_next_step=_recommended_next_step(none_count, full_count, partial_count),
    )


def serialize_business_qa_graph_coverage_report(
    report: BusinessQaGraphCoverageReport,
) -> dict[str, Any]:
    return asdict(report)


def coverage_label(
    expected_entities: list[str],
    expected_relations: list[str],
    missing_entities: list[str],
    missing_relations: list[str],
) -> str:
    expected_total = len(expected_entities) + len(expected_relations)
    missing_total = len(missing_entities) + len(missing_relations)
    if expected_total == 0:
        return PARTIAL
    if missing_total == 0:
        return FULL
    if missing_total == expected_total:
        return NONE
    return PARTIAL


def _coverage_reason(
    coverage_status: str,
    covered_entities: list[str],
    covered_relations: list[str],
    missing_entities: list[str],
    missing_relations: list[str],
) -> str:
    if coverage_status == FULL:
        return "Expected graph objects are covered by the selected subset."
    if coverage_status == NONE:
        return "Expected graph objects are not covered by the selected subset."
    return (
        f"Covered entities={len(covered_entities)}, "
        f"covered relations={len(covered_relations)}, "
        f"missing entities={len(missing_entities)}, "
        f"missing relations={len(missing_relations)}."
    )


def _coverage_risks(no_coverage_count: int, case_count: int) -> list[str]:
    risks: list[str] = []
    if no_coverage_count > 2:
        risks.append("Many cases have no graph subset coverage.")
    if case_count and no_coverage_count / case_count > 0.3:
        risks.append("Graph subset is likely too small for the case pack.")
    return risks


def _recommended_subset_limits(no_coverage_count: int) -> dict[str, int]:
    if no_coverage_count > 2:
        return {"max_chunks": 30, "max_entities": 60, "max_relationships": 40}
    return {"max_chunks": 15, "max_entities": 30, "max_relationships": 20}


def _recommended_next_step(
    no_coverage_count: int,
    full_coverage_count: int,
    partial_coverage_count: int,
) -> str:
    if no_coverage_count > 2 or full_coverage_count + partial_coverage_count < 7:
        return "EXPAND_GRAPH_SUBSET_BEFORE_EVAL"
    return "RUN_BUSINESS_QA_AB_EVAL"


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return numerator / denominator


__all__ = [
    "FULL",
    "NONE",
    "PARTIAL",
    "coverage_label",
    "evaluate_business_case_graph_coverage",
    "serialize_business_qa_graph_coverage_report",
]
