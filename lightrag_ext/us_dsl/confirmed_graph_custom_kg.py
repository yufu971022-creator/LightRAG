from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any

from .kg_metadata_sidecar import (
    OBJECT_KIND_CHUNK,
    OBJECT_KIND_ENTITY,
    OBJECT_KIND_RELATIONSHIP,
    GraphInsertSidecarAlignmentReport,
    KgMetadataSidecarRecord,
    chunk_external_key,
    entity_external_key,
    relationship_external_key,
    validate_graph_insert_sidecar_alignment,
)
from .kg_schema_policy import ALLOWED_ENTITY_TYPES, ALLOWED_RELATION_TYPES, FORBIDDEN_RELATION_TYPES
from .promotion_types import (
    ConfirmedGraphObject,
    ConfirmedGraphWritePlan,
    OBJECT_KIND_VERSION_RELATION,
)


@dataclass(frozen=True)
class ConfirmedCustomKgBuildReport:
    custom_kg_input: dict[str, list[dict[str, Any]]]
    issues: list[dict[str, Any]] = field(default_factory=list)


def to_confirmed_custom_kg_input(
    plan: ConfirmedGraphWritePlan,
    *,
    max_entities: int = 5,
    max_relationships: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    return build_confirmed_custom_kg_input_report(
        plan,
        max_entities=max_entities,
        max_relationships=max_relationships,
    ).custom_kg_input


def build_confirmed_custom_kg_input_report(
    plan: ConfirmedGraphWritePlan,
    *,
    max_entities: int = 5,
    max_relationships: int = 3,
) -> ConfirmedCustomKgBuildReport:
    issues: list[dict[str, Any]] = []
    confirmed_entities = plan.confirmed_entities[:max_entities]
    entity_by_name = {item.entity_name: item for item in confirmed_entities if item.entity_name}
    chunks: OrderedDict[str, dict[str, str]] = OrderedDict()
    entity_rows: list[dict[str, str]] = []

    for item in confirmed_entities:
        if not item.entity_name or not item.entity_type:
            issues.append(_issue("INVALID_CONFIRMED_ENTITY", "Confirmed entity is missing name/type."))
            continue
        if item.entity_type not in ALLOWED_ENTITY_TYPES:
            issues.append(_issue("INVALID_ENTITY_TYPE", f"Entity type {item.entity_type} is not allowed."))
            continue
        source_id = _source_id(item)
        chunks.setdefault(source_id, _chunk_row(item, source_id))
        entity_rows.append(
            {
                "entity_name": item.entity_name,
                "entity_type": item.entity_type,
                "description": _short_description(item.description or item.evidence.get("evidenceText")),
                "source_id": source_id,
            }
        )

    relationship_rows: list[dict[str, Any]] = []
    for item in [*plan.confirmed_relationships, *plan.confirmed_version_relations]:
        if len(relationship_rows) >= max_relationships:
            issues.append(_issue("CONFIRMED_RELATIONSHIP_LIMIT_APPLIED", "Relationship limit applied."))
            break
        relation_type = item.relation_type or ""
        if relation_type in FORBIDDEN_RELATION_TYPES or relation_type.lower() in FORBIDDEN_RELATION_TYPES:
            issues.append(_issue("FORBIDDEN_RELATION_BLOCKED", f"{relation_type} is forbidden."))
            continue
        if relation_type not in ALLOWED_RELATION_TYPES:
            issues.append(_issue("INVALID_RELATION_BLOCKED", f"{relation_type} is not allowed."))
            continue
        if item.object_kind == OBJECT_KIND_VERSION_RELATION:
            issues.append(_issue("VERSION_RELATION_BLOCKED", "Version relations are not written in Block 22A."))
            continue
        if item.src_id not in entity_by_name or item.tgt_id not in entity_by_name:
            issues.append(
                _issue(
                    "DANGLING_CONFIRMED_RELATIONSHIP_BLOCKED",
                    f"{item.src_id}->{item.tgt_id} has no approved endpoint entity.",
                )
            )
            continue
        source_id = _source_id(item)
        chunks.setdefault(source_id, _chunk_row(item, source_id))
        relationship_rows.append(
            {
                "src_id": str(item.src_id),
                "tgt_id": str(item.tgt_id),
                "description": _short_description(item.description or item.evidence.get("evidenceText")),
                "keywords": relation_type,
                "source_id": source_id,
                "weight": 1.0,
            }
        )

    source_ids = set(chunks)
    entity_rows = [row for row in entity_rows if row["source_id"] in source_ids]
    relationship_rows = [row for row in relationship_rows if row["source_id"] in source_ids]
    return ConfirmedCustomKgBuildReport(
        custom_kg_input={
            "chunks": list(chunks.values()),
            "entities": entity_rows,
            "relationships": relationship_rows,
        },
        issues=issues,
    )


def build_confirmed_graph_sidecar_records(
    plan: ConfirmedGraphWritePlan,
    custom_kg_input: dict[str, list[dict[str, Any]]],
    *,
    namespace: str,
) -> list[KgMetadataSidecarRecord]:
    object_by_entity_key = {
        entity_external_key(str(item.entity_type), str(item.entity_name), _source_id(item)): item
        for item in plan.confirmed_entities
        if item.entity_name and item.entity_type
    }
    object_by_relation_key = {
        relationship_external_key(str(item.src_id), str(item.tgt_id), str(item.relation_type), _source_id(item)): item
        for item in [*plan.confirmed_relationships, *plan.confirmed_version_relations]
        if item.src_id and item.tgt_id and item.relation_type
    }
    object_by_source: dict[str, ConfirmedGraphObject] = {}
    for item in [*plan.confirmed_entities, *plan.confirmed_relationships]:
        object_by_source.setdefault(_source_id(item), item)

    records: list[KgMetadataSidecarRecord] = []
    for chunk in custom_kg_input.get("chunks", []):
        source_id = str(chunk["source_id"])
        source_object = object_by_source.get(source_id)
        metadata = _metadata_for_object(plan, source_object, source_id=source_id)
        records.append(
            _record(
                object_kind=OBJECT_KIND_CHUNK,
                external_key=chunk_external_key(source_id),
                lightrag_ref_key=source_id,
                source_id=source_id,
                entity_name=None,
                entity_type=None,
                src_id=None,
                tgt_id=None,
                relation_type=None,
                keywords=None,
                metadata=metadata,
                payload=chunk,
                namespace=namespace,
            )
        )

    for entity in custom_kg_input.get("entities", []):
        key = entity_external_key(
            str(entity["entity_type"]),
            str(entity["entity_name"]),
            str(entity["source_id"]),
        )
        source_object = object_by_entity_key.get(key)
        metadata = _metadata_for_object(plan, source_object, source_id=str(entity["source_id"]))
        records.append(
            _record(
                object_kind=OBJECT_KIND_ENTITY,
                external_key=key,
                lightrag_ref_key=str(entity["entity_name"]),
                source_id=str(entity["source_id"]),
                entity_name=str(entity["entity_name"]),
                entity_type=str(entity["entity_type"]),
                src_id=None,
                tgt_id=None,
                relation_type=None,
                keywords=None,
                metadata=metadata,
                payload=entity,
                namespace=namespace,
            )
        )

    for relationship in custom_kg_input.get("relationships", []):
        relation_type = str(relationship["keywords"])
        key = relationship_external_key(
            str(relationship["src_id"]),
            str(relationship["tgt_id"]),
            relation_type,
            str(relationship["source_id"]),
        )
        source_object = object_by_relation_key.get(key)
        metadata = _metadata_for_object(plan, source_object, source_id=str(relationship["source_id"]))
        metadata["relationType"] = relation_type
        records.append(
            _record(
                object_kind=OBJECT_KIND_RELATIONSHIP,
                external_key=key,
                lightrag_ref_key=f"{relationship['src_id']}->{relationship['tgt_id']}",
                source_id=str(relationship["source_id"]),
                entity_name=None,
                entity_type=None,
                src_id=str(relationship["src_id"]),
                tgt_id=str(relationship["tgt_id"]),
                relation_type=relation_type,
                keywords=relation_type,
                metadata=metadata,
                payload=relationship,
                namespace=namespace,
            )
        )

    return records


def validate_confirmed_sidecar_alignment(
    custom_kg_input: dict[str, list[dict[str, Any]]],
    records: list[KgMetadataSidecarRecord],
) -> GraphInsertSidecarAlignmentReport:
    return validate_graph_insert_sidecar_alignment(custom_kg_input, records)


def serialize_confirmed_custom_kg_build_report(report: ConfirmedCustomKgBuildReport) -> dict[str, Any]:
    return asdict(report)


def _metadata_for_object(
    plan: ConfirmedGraphWritePlan,
    item: ConfirmedGraphObject | None,
    *,
    source_id: str,
) -> dict[str, Any]:
    evidence = dict(item.evidence) if item is not None else {}
    audit = dict(item.audit_metadata) if item is not None else {}
    return {
        "documentId": audit.get("documentId"),
        "sourceUsId": evidence.get("sourceUsId"),
        "textUnitId": evidence.get("textUnitId") or source_id,
        "source_id": source_id,
        "sourceSpan": evidence.get("sourceSpan"),
        "textHash": evidence.get("textHash"),
        "evidenceText": evidence.get("evidenceText"),
        "featureKey": audit.get("featureKey"),
        "domainCode": audit.get("domainCode"),
        "sectionType": audit.get("sectionType"),
        "knowledgeStatus": "ConfirmedGraphPlan",
        "validationStatus": "VALID",
        "reviewDecision": "APPROVED",
        "confidenceScore": None,
        "manifestId": audit.get("manifestId"),
        "reviewer": audit.get("reviewer"),
        "decisionReason": audit.get("decisionReason"),
        "evidenceChecked": audit.get("evidenceChecked"),
        "versionChecked": audit.get("versionChecked"),
        "termChecked": audit.get("termChecked"),
        "idempotencyKey": item.idempotency_key if item is not None else None,
        "rollbackKey": item.rollback_key if item is not None else None,
        "auditEventIds": [event.event_id for event in plan.audit_events],
        "ruleVersion": (item.version_metadata.get("ruleVersion") if item is not None else None),
        "latestFlag": (item.version_metadata.get("latestFlag") if item is not None else None),
        "versionStatus": (item.version_metadata.get("versionStatus") if item is not None else None),
        "supersedes": (item.version_metadata.get("supersedes") if item is not None else None),
        "originalTerm": (item.term_metadata.get("originalTerm") if item is not None else None),
        "canonicalTerm": (item.term_metadata.get("canonicalTerm") if item is not None else None),
        "candidateId": audit.get("candidateId"),
        "extractionRunId": None,
        "pilotReportId": None,
    }


def _record(
    *,
    object_kind: str,
    external_key: str,
    lightrag_ref_key: str | None,
    source_id: str | None,
    entity_name: str | None,
    entity_type: str | None,
    src_id: str | None,
    tgt_id: str | None,
    relation_type: str | None,
    keywords: str | None,
    metadata: dict[str, Any],
    payload: dict[str, Any],
    namespace: str,
) -> KgMetadataSidecarRecord:
    return KgMetadataSidecarRecord(
        sidecar_id=_stable_hash("confirmed-sidecar", namespace, object_kind, external_key),
        object_kind=object_kind,
        external_key=external_key,
        lightrag_ref_key=lightrag_ref_key,
        source_id=source_id,
        entity_name=entity_name,
        entity_type=entity_type,
        src_id=src_id,
        tgt_id=tgt_id,
        relation_type=relation_type,
        keywords=keywords,
        metadata=metadata,
        metadata_hash=_dict_hash(metadata),
        payload_hash=_dict_hash(payload),
        namespace=namespace,
        created_at="1970-01-01T00:00:00+00:00",
    )


def _chunk_row(item: ConfirmedGraphObject, source_id: str) -> dict[str, str]:
    return {
        "content": str(item.evidence.get("evidenceText") or item.description or ""),
        "source_id": source_id,
    }


def _source_id(item: ConfirmedGraphObject) -> str:
    return str(item.evidence.get("textUnitId") or item.evidence.get("source_id") or item.source_id or "UNKNOWN")


def _short_description(value: Any, *, limit: int = 500) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit]


def _dict_hash(value: dict[str, Any]) -> str:
    return _stable_hash(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _stable_hash(*parts: Any) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": message}


__all__ = [
    "ConfirmedCustomKgBuildReport",
    "build_confirmed_custom_kg_input_report",
    "build_confirmed_graph_sidecar_records",
    "serialize_confirmed_custom_kg_build_report",
    "to_confirmed_custom_kg_input",
    "validate_confirmed_sidecar_alignment",
]
