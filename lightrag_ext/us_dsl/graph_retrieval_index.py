from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .kg_metadata_sidecar import (
    KgMetadataSidecarRecord,
    chunk_external_key,
    entity_external_key,
    relationship_external_key,
)
from .kg_payload_types import DslKgPayload, KgEntity, KgRelationship


@dataclass(frozen=True)
class TextEvidenceRecord:
    external_key: str
    source_id: str
    evidence_text: str
    source_us_id: str | None
    text_unit_id: str | None
    source_span: dict[str, Any] | None
    text_hash: str | None
    domain_code: str | None
    feature_key: str | None
    section_type: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class KgNodeRecord:
    external_key: str
    entity_name: str
    entity_type: str
    description: str
    source_id: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class KgEdgeRecord:
    external_key: str
    src_id: str
    tgt_id: str
    relation_type: str
    description: str
    source_id: str
    weight: float
    metadata: dict[str, Any]


@dataclass
class TextEvidenceIndex:
    records: list[TextEvidenceRecord]
    by_source_id: dict[str, list[TextEvidenceRecord]]


@dataclass
class KgNodeIndex:
    records: list[KgNodeRecord]
    by_name: dict[str, list[KgNodeRecord]]


@dataclass
class KgEdgeIndex:
    records: list[KgEdgeRecord]
    by_relation_type: dict[str, list[KgEdgeRecord]]
    by_entity_name: dict[str, list[KgEdgeRecord]]


@dataclass
class GraphPathIndex:
    adjacency: dict[str, list[KgEdgeRecord]]
    reverse_adjacency: dict[str, list[KgEdgeRecord]]

    def retrieve_paths(
        self,
        seed_entities: list[str],
        *,
        max_hops: int = 2,
        max_paths: int = 5,
    ) -> list[list[KgEdgeRecord]]:
        paths: list[list[KgEdgeRecord]] = []
        seen: set[tuple[str, ...]] = set()
        for seed in seed_entities:
            for edge in self._neighbors(seed):
                self._append_path(paths, seen, [edge], max_paths)
                if len(paths) >= max_paths:
                    return paths
                if max_hops < 2:
                    continue
                next_node = edge.tgt_id if edge.src_id == seed else edge.src_id
                for second_edge in self._neighbors(next_node):
                    if second_edge == edge:
                        continue
                    self._append_path(paths, seen, [edge, second_edge], max_paths)
                    if len(paths) >= max_paths:
                        return paths
        return paths

    def _neighbors(self, entity_name: str) -> list[KgEdgeRecord]:
        return [
            *self.adjacency.get(entity_name, []),
            *self.reverse_adjacency.get(entity_name, []),
        ]

    @staticmethod
    def _append_path(
        paths: list[list[KgEdgeRecord]],
        seen: set[tuple[str, ...]],
        path: list[KgEdgeRecord],
        max_paths: int,
    ) -> None:
        key = tuple(edge.external_key for edge in path)
        if key in seen or len(paths) >= max_paths:
            return
        seen.add(key)
        paths.append(path)


@dataclass
class GraphRetrievalIndexes:
    text_index: TextEvidenceIndex
    node_index: KgNodeIndex
    edge_index: KgEdgeIndex
    path_index: GraphPathIndex


def build_graph_retrieval_indexes(
    payload: DslKgPayload,
    sidecar_records: list[KgMetadataSidecarRecord],
) -> GraphRetrievalIndexes:
    sidecar_by_key = {record.external_key: record for record in sidecar_records}
    text_records = _build_text_records(payload, sidecar_by_key)
    node_records = _build_node_records(payload.entities, sidecar_by_key)
    edge_records = _build_edge_records(payload.relationships, sidecar_by_key)
    return GraphRetrievalIndexes(
        text_index=TextEvidenceIndex(
            records=text_records,
            by_source_id=_group_text_by_source(text_records),
        ),
        node_index=KgNodeIndex(
            records=node_records,
            by_name=_group_nodes_by_name(node_records),
        ),
        edge_index=KgEdgeIndex(
            records=edge_records,
            by_relation_type=_group_edges_by_relation(edge_records),
            by_entity_name=_group_edges_by_entity(edge_records),
        ),
        path_index=_build_path_index(edge_records),
    )


def node_record_to_path_item(record: KgNodeRecord) -> dict[str, Any]:
    return {
        "entity_name": record.entity_name,
        "entity_type": record.entity_type,
        "source_id": record.source_id,
    }


def edge_record_to_path_item(record: KgEdgeRecord) -> dict[str, Any]:
    return {
        "src_id": record.src_id,
        "tgt_id": record.tgt_id,
        "relation_type": record.relation_type,
        "source_id": record.source_id,
    }


def _build_text_records(
    payload: DslKgPayload,
    sidecar_by_key: dict[str, KgMetadataSidecarRecord],
) -> list[TextEvidenceRecord]:
    records: list[TextEvidenceRecord] = []
    seen: set[str] = set()
    for chunk in payload.chunks:
        key = chunk_external_key(chunk.source_id)
        metadata = _merged_metadata(chunk.metadata, sidecar_by_key.get(key))
        records.append(
            _text_record(
                external_key=key,
                source_id=chunk.source_id,
                evidence_text=str(metadata.get("evidenceText") or chunk.content),
                metadata=metadata,
            )
        )
        seen.add(key)

    for record in sidecar_by_key.values():
        evidence_text = record.metadata.get("evidenceText")
        if not evidence_text or record.external_key in seen:
            continue
        if record.object_kind not in {"entity", "relationship"}:
            continue
        records.append(
            _text_record(
                external_key=record.external_key,
                source_id=record.source_id or str(record.external_key),
                evidence_text=str(evidence_text),
                metadata=record.metadata,
            )
        )
        seen.add(record.external_key)
    return records


def _build_node_records(
    entities: list[KgEntity],
    sidecar_by_key: dict[str, KgMetadataSidecarRecord],
) -> list[KgNodeRecord]:
    records: list[KgNodeRecord] = []
    for entity in entities:
        key = entity_external_key(entity.entity_type, entity.entity_name, entity.source_id)
        metadata = _merged_metadata(entity.metadata, sidecar_by_key.get(key))
        records.append(
            KgNodeRecord(
                external_key=key,
                entity_name=entity.entity_name,
                entity_type=entity.entity_type,
                description=entity.description,
                source_id=entity.source_id,
                metadata=metadata,
            )
        )
    return records


def _build_edge_records(
    relationships: list[KgRelationship],
    sidecar_by_key: dict[str, KgMetadataSidecarRecord],
) -> list[KgEdgeRecord]:
    records: list[KgEdgeRecord] = []
    for relationship in relationships:
        relation_type = str(
            relationship.metadata.get("relationType") or relationship.keywords
        )
        key = relationship_external_key(
            relationship.src_id,
            relationship.tgt_id,
            relation_type,
            relationship.source_id,
        )
        metadata = _merged_metadata(relationship.metadata, sidecar_by_key.get(key))
        records.append(
            KgEdgeRecord(
                external_key=key,
                src_id=relationship.src_id,
                tgt_id=relationship.tgt_id,
                relation_type=relation_type,
                description=relationship.description,
                source_id=relationship.source_id,
                weight=relationship.weight,
                metadata=metadata,
            )
        )
    return records


def _text_record(
    *,
    external_key: str,
    source_id: str,
    evidence_text: str,
    metadata: dict[str, Any],
) -> TextEvidenceRecord:
    return TextEvidenceRecord(
        external_key=external_key,
        source_id=source_id,
        evidence_text=evidence_text,
        source_us_id=_string_or_none(metadata.get("sourceUsId")),
        text_unit_id=_string_or_none(metadata.get("textUnitId")),
        source_span=_dict_or_none(metadata.get("sourceSpan")),
        text_hash=_string_or_none(metadata.get("textHash")),
        domain_code=_string_or_none(metadata.get("domainCode")),
        feature_key=_string_or_none(metadata.get("featureKey")),
        section_type=_string_or_none(metadata.get("sectionType")),
        metadata=metadata,
    )


def _merged_metadata(
    fallback: dict[str, Any],
    sidecar_record: KgMetadataSidecarRecord | None,
) -> dict[str, Any]:
    if sidecar_record is None:
        return dict(fallback)
    return {**dict(fallback), **dict(sidecar_record.metadata)}


def _group_text_by_source(
    records: list[TextEvidenceRecord],
) -> dict[str, list[TextEvidenceRecord]]:
    grouped: dict[str, list[TextEvidenceRecord]] = defaultdict(list)
    for record in records:
        grouped[record.source_id].append(record)
    return dict(grouped)


def _group_nodes_by_name(
    records: list[KgNodeRecord],
) -> dict[str, list[KgNodeRecord]]:
    grouped: dict[str, list[KgNodeRecord]] = defaultdict(list)
    for record in records:
        grouped[record.entity_name].append(record)
    return dict(grouped)


def _group_edges_by_relation(
    records: list[KgEdgeRecord],
) -> dict[str, list[KgEdgeRecord]]:
    grouped: dict[str, list[KgEdgeRecord]] = defaultdict(list)
    for record in records:
        grouped[record.relation_type].append(record)
    return dict(grouped)


def _group_edges_by_entity(
    records: list[KgEdgeRecord],
) -> dict[str, list[KgEdgeRecord]]:
    grouped: dict[str, list[KgEdgeRecord]] = defaultdict(list)
    for record in records:
        grouped[record.src_id].append(record)
        grouped[record.tgt_id].append(record)
    return dict(grouped)


def _build_path_index(records: list[KgEdgeRecord]) -> GraphPathIndex:
    adjacency: dict[str, list[KgEdgeRecord]] = defaultdict(list)
    reverse: dict[str, list[KgEdgeRecord]] = defaultdict(list)
    for record in records:
        adjacency[record.src_id].append(record)
        reverse[record.tgt_id].append(record)
    return GraphPathIndex(dict(adjacency), dict(reverse))


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


__all__ = [
    "GraphPathIndex",
    "GraphRetrievalIndexes",
    "KgEdgeIndex",
    "KgEdgeRecord",
    "KgNodeIndex",
    "KgNodeRecord",
    "TextEvidenceIndex",
    "TextEvidenceRecord",
    "build_graph_retrieval_indexes",
    "edge_record_to_path_item",
    "node_record_to_path_item",
]
