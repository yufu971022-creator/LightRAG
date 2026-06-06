from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .business_qa_coverage import evaluate_business_case_graph_coverage
from .business_qa_types import BusinessQaGraphCoverageReport
from .kg_metadata_sidecar import (
    KgMetadataSidecarRecord,
    build_graph_insert_sidecar_records,
    validate_graph_insert_sidecar_alignment,
)
from .kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship
from .kg_schema_policy import FORBIDDEN_RELATION_TYPES
from .kg_test_graph_write import to_lightrag_custom_kg_input


LC_EXPANDED_SUBSET_NAMESPACE = "dsl_test_lc_expanded_graph_subset"


@dataclass(frozen=True)
class ExpandedGraphSubsetResult:
    custom_kg_input: dict[str, list[dict[str, Any]]]
    subset_payload: DslKgPayload
    graph_insert_sidecar_records: list[KgMetadataSidecarRecord]
    coverage_report: BusinessQaGraphCoverageReport
    selected_chunk_count: int
    selected_entity_count: int
    selected_relationship_count: int
    sidecar_alignment_passed: bool
    dangling_relationship_count: int
    forbidden_relation_count: int
    confirmed_count: int
    review_required_written: bool
    info_only_written: bool
    risks: list[str] = field(default_factory=list)


def build_lc_expanded_graph_subset_from_case_pack(
    *,
    kg_payload: DslKgPayload,
    cases: list[Any],
    max_chunks: int = 15,
    max_entities: int = 30,
    max_relationships: int = 20,
    namespace: str = LC_EXPANDED_SUBSET_NAMESPACE,
) -> ExpandedGraphSubsetResult:
    selected_entities, selected_relationships, risks = _select_case_driven_objects(
        kg_payload,
        cases,
        max_entities=max_entities,
        max_relationships=max_relationships,
    )
    selected_chunks, selected_entities, selected_relationships = _select_chunks_and_filter(
        kg_payload,
        selected_entities,
        selected_relationships,
        max_chunks=max_chunks,
        risks=risks,
    )
    subset_payload = _subset_payload(
        kg_payload,
        chunks=selected_chunks,
        entities=selected_entities,
        relationships=selected_relationships,
        max_chunks=max_chunks,
        max_entities=max_entities,
        max_relationships=max_relationships,
        risks=risks,
    )
    custom_kg = to_lightrag_custom_kg_input(subset_payload)
    sidecar_records = build_graph_insert_sidecar_records(
        subset_payload,
        custom_kg,
        namespace=namespace,
    )
    alignment = validate_graph_insert_sidecar_alignment(custom_kg, sidecar_records)
    dangling_count = _dangling_relationship_count(custom_kg)
    forbidden_count = sum(
        1
        for relationship in subset_payload.relationships
        if relationship.keywords in FORBIDDEN_RELATION_TYPES
    )
    status_counts = _status_counts(subset_payload)
    coverage_report = evaluate_business_case_graph_coverage(
        cases,
        subset_payload,
        module_name="LC",
        case_pack_name="LC_BUSINESS_QA",
        selected_chunk_count=len(subset_payload.chunks),
        selected_entity_count=len(subset_payload.entities),
        selected_relationship_count=len(subset_payload.relationships),
    )
    risks.extend(coverage_report.risks)
    if alignment.pass_status != "PASS":
        risks.append("Graph insert sidecar alignment failed.")
    if dangling_count:
        risks.append(f"Dangling relationship count is {dangling_count}.")
    if forbidden_count:
        risks.append(f"Forbidden relation count is {forbidden_count}.")

    return ExpandedGraphSubsetResult(
        custom_kg_input=custom_kg,
        subset_payload=subset_payload,
        graph_insert_sidecar_records=sidecar_records,
        coverage_report=coverage_report,
        selected_chunk_count=len(subset_payload.chunks),
        selected_entity_count=len(subset_payload.entities),
        selected_relationship_count=len(subset_payload.relationships),
        sidecar_alignment_passed=alignment.pass_status == "PASS",
        dangling_relationship_count=dangling_count,
        forbidden_relation_count=forbidden_count,
        confirmed_count=status_counts["confirmed"],
        review_required_written=status_counts["review_required"] > 0,
        info_only_written=status_counts["info_only"] > 0,
        risks=risks,
    )


def _select_case_driven_objects(
    payload: DslKgPayload,
    cases: list[Any],
    *,
    max_entities: int,
    max_relationships: int,
) -> tuple[list[KgEntity], list[KgRelationship], list[str]]:
    risks: list[str] = []
    entity_by_name = _entity_by_name(payload.entities)
    entity_priority = _expected_entity_priority(cases)
    relation_priority = _expected_relation_priority(cases)
    domain_priority = _expected_attr_priority(cases, "expected_domains")
    section_priority = _expected_attr_priority(cases, "expected_sections")

    selected_entities: list[KgEntity] = []
    for entity_name, _priority in sorted(
        entity_priority.items(),
        key=lambda item: (-item[1], item[0]),
    ):
        entity = entity_by_name.get(entity_name)
        if entity is not None:
            _append_entity(selected_entities, entity, max_entities=max_entities)

    relationship_candidates = sorted(
        [
            (relationship, _relationship_score(
                relationship,
                entity_priority=entity_priority,
                relation_priority=relation_priority,
                domain_priority=domain_priority,
                section_priority=section_priority,
            ))
            for relationship in payload.relationships
        ],
        key=lambda item: (-item[1], item[0].src_id, item[0].keywords, item[0].tgt_id),
    )

    selected_relationships: list[KgRelationship] = []
    for relationship, score in relationship_candidates:
        if score <= 0 or len(selected_relationships) >= max_relationships:
            continue
        if _version_relation_limit_reached(selected_relationships, relationship.keywords):
            continue
        endpoints = [
            entity_by_name.get(relationship.src_id),
            entity_by_name.get(relationship.tgt_id),
        ]
        if any(entity is None for entity in endpoints):
            risks.append(
                f"Relationship dropped because endpoint is missing: "
                f"{relationship.src_id}->{relationship.tgt_id}."
            )
            continue
        prospective = list(selected_entities)
        for entity in endpoints:
            if entity is not None:
                _append_entity(prospective, entity, max_entities=max_entities)
        if len(prospective) > max_entities:
            risks.append(
                f"Relationship dropped due to entity limit: "
                f"{relationship.src_id}->{relationship.tgt_id}."
            )
            continue
        selected_entities = prospective
        selected_relationships.append(relationship)

    if len(selected_relationships) == max_relationships and len(relationship_candidates) > max_relationships:
        risks.append(f"Relationship candidates truncated to {max_relationships}.")
    return selected_entities[:max_entities], selected_relationships[:max_relationships], risks


def _select_chunks_and_filter(
    payload: DslKgPayload,
    selected_entities: list[KgEntity],
    selected_relationships: list[KgRelationship],
    *,
    max_chunks: int,
    risks: list[str],
) -> tuple[list[KgChunk], list[KgEntity], list[KgRelationship]]:
    chunk_by_id = {chunk.source_id: chunk for chunk in payload.chunks}
    source_scores: dict[str, int] = {}
    for index, relationship in enumerate(selected_relationships):
        score = 10_000 - index
        source_scores[relationship.source_id] = max(source_scores.get(relationship.source_id, 0), score)
        for entity in selected_entities:
            if entity.entity_name in {relationship.src_id, relationship.tgt_id}:
                source_scores[entity.source_id] = max(source_scores.get(entity.source_id, 0), score)
    for index, entity in enumerate(selected_entities):
        source_scores[entity.source_id] = max(source_scores.get(entity.source_id, 0), 1_000 - index)

    source_ids = [
        source_id
        for source_id, _score in sorted(
            source_scores.items(),
            key=lambda item: (-item[1], item[0]),
        )
        if source_id in chunk_by_id
    ]
    if len(source_ids) > max_chunks:
        risks.append(f"Chunk candidates truncated from {len(source_ids)} to {max_chunks}.")
        source_ids = source_ids[:max_chunks]

    selected_chunks = [chunk_by_id[source_id] for source_id in source_ids]
    selected_chunk_ids = {chunk.source_id for chunk in selected_chunks}
    filtered_entities = [
        entity for entity in selected_entities if entity.source_id in selected_chunk_ids
    ]
    entity_names = {entity.entity_name for entity in filtered_entities}
    filtered_relationships = [
        relationship
        for relationship in selected_relationships
        if relationship.source_id in selected_chunk_ids
        and relationship.src_id in entity_names
        and relationship.tgt_id in entity_names
    ]
    return selected_chunks, filtered_entities, filtered_relationships


def _subset_payload(
    full_payload: DslKgPayload,
    *,
    chunks: list[KgChunk],
    entities: list[KgEntity],
    relationships: list[KgRelationship],
    max_chunks: int,
    max_entities: int,
    max_relationships: int,
    risks: list[str],
) -> DslKgPayload:
    return DslKgPayload(
        chunks=chunks,
        entities=entities,
        relationships=relationships,
        metadata={
            **full_payload.metadata,
            "caseDrivenSubset": True,
            "maxChunks": max_chunks,
            "maxEntities": max_entities,
            "maxRelationships": max_relationships,
            "subsetRisks": list(risks),
        },
        issues=list(full_payload.issues),
        summary={
            **full_payload.summary,
            "selected_chunk_count": len(chunks),
            "selected_entity_count": len(entities),
            "selected_relationship_count": len(relationships),
            "graph_write_called": False,
            "case_driven_subset": True,
        },
        entity_vdb_payload=[],
        relationship_vdb_payload=[],
        evidence_mapping=dict(full_payload.evidence_mapping),
        version_mapping=dict(full_payload.version_mapping),
    )


def _relationship_score(
    relationship: KgRelationship,
    *,
    entity_priority: dict[str, int],
    relation_priority: dict[str, int],
    domain_priority: dict[str, int],
    section_priority: dict[str, int],
) -> int:
    score = 0
    if relationship.keywords in relation_priority:
        score += 10_000 + relation_priority[relationship.keywords]
    endpoint_score = max(
        entity_priority.get(relationship.src_id, 0),
        entity_priority.get(relationship.tgt_id, 0),
    )
    if endpoint_score:
        score += 5_000 + endpoint_score
    domain = str(relationship.metadata.get("domainCode") or "")
    section = str(relationship.metadata.get("sectionType") or "")
    score += domain_priority.get(domain, 0)
    score += section_priority.get(section, 0)
    return score


def _version_relation_limit_reached(
    selected_relationships: list[KgRelationship],
    relation_type: str,
) -> bool:
    if relation_type not in {
        "HasVersion",
        "VersionReviewRequired",
        "VersionConflictWith",
        "Supersedes",
    }:
        return False
    return sum(1 for item in selected_relationships if item.keywords == relation_type) >= 2


def _expected_entity_priority(cases: list[Any]) -> dict[str, int]:
    priorities: dict[str, int] = {}
    for case in cases:
        score = _case_score(case)
        for entity in getattr(case, "expected_entities", []):
            priorities[entity] = max(priorities.get(entity, 0), score)
    return priorities


def _expected_relation_priority(cases: list[Any]) -> dict[str, int]:
    priorities: dict[str, int] = {}
    for case in cases:
        score = _case_score(case) + 500
        for relation in getattr(case, "expected_relations", []):
            priorities[relation] = max(priorities.get(relation, 0), score)
    return priorities


def _expected_attr_priority(cases: list[Any], attr_name: str) -> dict[str, int]:
    priorities: dict[str, int] = {}
    for case in cases:
        score = _case_score(case)
        for value in getattr(case, attr_name, []):
            priorities[value] = max(priorities.get(value, 0), score)
    return priorities


def _case_score(case: Any) -> int:
    level = str(getattr(case, "level", "L1")).upper()
    if level == "L2":
        return 300
    if level == "L1":
        return 200
    return 100


def _entity_by_name(entities: list[KgEntity]) -> dict[str, KgEntity]:
    by_name: dict[str, KgEntity] = {}
    for entity in entities:
        by_name.setdefault(entity.entity_name, entity)
    return by_name


def _append_entity(
    values: list[KgEntity],
    entity: KgEntity,
    *,
    max_entities: int,
) -> None:
    if len(values) >= max_entities:
        return
    if entity.entity_name in {item.entity_name for item in values}:
        return
    values.append(entity)


def _dangling_relationship_count(custom_kg: dict[str, list[dict[str, Any]]]) -> int:
    entity_names = {item["entity_name"] for item in custom_kg["entities"]}
    return sum(
        1
        for relationship in custom_kg["relationships"]
        if relationship["src_id"] not in entity_names
        or relationship["tgt_id"] not in entity_names
    )


def _status_counts(payload: DslKgPayload) -> dict[str, int]:
    statuses = [
        str(item.metadata.get("knowledgeStatus") or "")
        for item in [*payload.entities, *payload.relationships]
    ]
    return {
        "confirmed": sum(status == "Confirmed" for status in statuses),
        "review_required": sum(status == "ReviewRequired" for status in statuses),
        "info_only": sum(status == "InfoOnly" for status in statuses),
    }


__all__ = [
    "ExpandedGraphSubsetResult",
    "LC_EXPANDED_SUBSET_NAMESPACE",
    "build_lc_expanded_graph_subset_from_case_pack",
]
