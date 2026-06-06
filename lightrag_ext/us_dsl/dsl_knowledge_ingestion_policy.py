from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
from typing import Any

from .domain_registry import DomainRegistry, default_domain_registry
from .kg_metadata_sidecar import (
    KgMetadataSidecarRecord,
    build_graph_insert_sidecar_records,
    build_metadata_sidecar_records,
    entity_external_key,
    relationship_external_key,
    validate_graph_insert_sidecar_alignment,
)
from .kg_payload_types import DslKgPayload, KgEntity, KgRelationship
from .kg_schema_policy import FORBIDDEN_RELATION_TYPES
from .kg_test_graph_write import to_lightrag_custom_kg_input
from .policy_auto_approval import PolicyAutoApprovalConfig, run_policy_auto_approval
from .promotion_gate import build_promotion_candidates


BLOCK_REVIEW_REQUIRED = "REVIEW_REQUIRED_BLOCKED"
BLOCK_INFO_ONLY = "INFO_ONLY_BLOCKED"
BLOCK_VERSION_REVIEW_REQUIRED = "VERSION_REVIEW_REQUIRED_BLOCKED"
BLOCK_VERSION_CONFLICT = "VERSION_CONFLICT_BLOCKED"
BLOCK_MISSING_EVIDENCE = "MISSING_EVIDENCE"
BLOCK_INVALID_RELATION = "INVALID_RELATION_BLOCKED"
BLOCK_FORBIDDEN_RELATION = "FORBIDDEN_RELATION_BLOCKED"
BLOCK_DANGLING_RELATION = "DANGLING_RELATIONSHIP_BLOCKED"


@dataclass(frozen=True)
class PreparedIngestionPayload:
    approved_payload: DslKgPayload
    custom_kg_input: dict[str, list[dict[str, Any]]]
    sidecar_records: list[KgMetadataSidecarRecord]
    sidecar_alignment_passed: bool
    endpoint_closure_passed: bool
    dangling_relationship_count: int
    forbidden_relation_count: int
    idempotency_keys: list[str]
    idempotency_key_duplicate_count: int
    block_reason_distribution: dict[str, int]
    approved_entity_count: int
    approved_relationship_count: int
    blocked_object_count: int
    blocked_reason_occurrence_count: int
    blocked_count: int
    rollback_keys: list[str]
    rollback_plan_present: bool
    rollback_key_count: int
    rollback_strategy: str | None
    dropped_relationship_due_to_endpoint_count: int
    evidence_missing_count: int
    version_review_required_blocked_count: int
    review_required_blocked_count: int
    info_only_blocked_count: int
    invalid_relation_blocked_count: int
    forbidden_relation_blocked_count: int
    dangling_relationship_blocked_count: int
    issues: list[dict[str, Any]]
    risks: list[str]


def prepare_policy_approved_ingestion_payload(
    payload: DslKgPayload,
    *,
    namespace: str,
    registry: DomainRegistry | None = None,
) -> PreparedIngestionPayload:
    registry = registry or default_domain_registry()
    full_records = build_metadata_sidecar_records(payload, namespace=namespace)
    candidates = build_promotion_candidates(kg_payload=payload, sidecar_records=full_records)
    policy_result = run_policy_auto_approval(
        candidates,
        config=PolicyAutoApprovalConfig(namespace=namespace),
        module_name=str(payload.metadata.get("moduleName") or "module"),
        source_document=str(payload.metadata.get("source") or ""),
    )
    approved_keys = {
        candidate.rollback_key
        for candidate in policy_result.approved_candidates
        if candidate.rollback_key
    }
    idempotency_by_key = {
        str(candidate.rollback_key): str(candidate.idempotency_key)
        for candidate in policy_result.approved_candidates
        if candidate.rollback_key and candidate.idempotency_key
    }
    block_reasons = Counter(policy_result.block_reason_distribution)

    selected_entities: list[KgEntity] = []
    for entity in payload.entities:
        key = entity_external_key(entity.entity_type, entity.entity_name, entity.source_id)
        blockers = _entity_blockers(entity, registry)
        if key in approved_keys and not blockers:
            selected_entities.append(entity)
        else:
            block_reasons.update(blockers or ([] if key in approved_keys else ["POLICY_NOT_APPROVED"]))

    selected_entity_names = {entity.entity_name for entity in selected_entities}
    selected_relationships: list[KgRelationship] = []
    dropped_relationship_due_to_endpoint_count = 0
    for relationship in payload.relationships:
        relation_type = str(relationship.metadata.get("relationType") or relationship.keywords)
        key = relationship_external_key(
            relationship.src_id,
            relationship.tgt_id,
            relation_type,
            relationship.source_id,
        )
        blockers = _relationship_blockers(relationship, registry)
        endpoints_present = (
            relationship.src_id in selected_entity_names
            and relationship.tgt_id in selected_entity_names
        )
        if not endpoints_present:
            blockers.append(BLOCK_DANGLING_RELATION)
            if key in approved_keys:
                dropped_relationship_due_to_endpoint_count += 1
        if key in approved_keys and not blockers:
            selected_relationships.append(relationship)
        else:
            block_reasons.update(blockers or ([] if key in approved_keys else ["POLICY_NOT_APPROVED"]))

    source_ids = {
        item.source_id for item in selected_entities
    } | {item.source_id for item in selected_relationships}
    selected_chunks = [chunk for chunk in payload.chunks if chunk.source_id in source_ids]
    approved_payload = DslKgPayload(
        chunks=selected_chunks,
        entities=selected_entities,
        relationships=selected_relationships,
        metadata={**payload.metadata, "policyApprovedForTestGraph": True},
        issues=list(payload.issues),
        summary={
            **payload.summary,
            "approved_entity_count": len(selected_entities),
            "approved_relationship_count": len(selected_relationships),
        },
        entity_vdb_payload=list(payload.entity_vdb_payload),
        relationship_vdb_payload=list(payload.relationship_vdb_payload),
        evidence_mapping=dict(payload.evidence_mapping),
        version_mapping=dict(payload.version_mapping),
    )
    custom_kg = to_lightrag_custom_kg_input(approved_payload)
    sidecar_records = build_graph_insert_sidecar_records(
        approved_payload,
        custom_kg,
        namespace=namespace,
    )
    sidecar_records = _enrich_sidecar_records(
        sidecar_records,
        idempotency_by_key=idempotency_by_key,
        namespace=namespace,
    )
    alignment = validate_graph_insert_sidecar_alignment(custom_kg, sidecar_records)
    idempotency_keys = [
        str(record.metadata.get("idempotencyKey"))
        for record in sidecar_records
        if record.metadata.get("idempotencyKey")
    ]
    rollback_keys = [
        str(record.metadata.get("rollbackKey"))
        for record in sidecar_records
        if record.metadata.get("rollbackKey")
    ]
    duplicate_count = _duplicate_count(idempotency_keys)
    blocked_object_count = (
        len(payload.entities)
        + len(payload.relationships)
        - len(selected_entities)
        - len(selected_relationships)
    )
    blocked_reason_occurrence_count = sum(block_reasons.values())
    return PreparedIngestionPayload(
        approved_payload=approved_payload,
        custom_kg_input=custom_kg,
        sidecar_records=sidecar_records,
        sidecar_alignment_passed=alignment.pass_status == "PASS",
        endpoint_closure_passed=_dangling_custom_kg_count(custom_kg) == 0,
        dangling_relationship_count=_dangling_custom_kg_count(custom_kg),
        forbidden_relation_count=_forbidden_count(custom_kg),
        idempotency_keys=idempotency_keys,
        idempotency_key_duplicate_count=duplicate_count,
        block_reason_distribution=dict(block_reasons),
        approved_entity_count=len(selected_entities),
        approved_relationship_count=len(selected_relationships),
        blocked_object_count=blocked_object_count,
        blocked_reason_occurrence_count=blocked_reason_occurrence_count,
        blocked_count=blocked_object_count,
        rollback_keys=rollback_keys,
        rollback_plan_present=_rollback_plan_present(custom_kg, rollback_keys),
        rollback_key_count=len(rollback_keys),
        rollback_strategy="delete_by_id" if rollback_keys else None,
        dropped_relationship_due_to_endpoint_count=dropped_relationship_due_to_endpoint_count,
        evidence_missing_count=block_reasons[BLOCK_MISSING_EVIDENCE],
        version_review_required_blocked_count=block_reasons[BLOCK_VERSION_REVIEW_REQUIRED]
        + block_reasons[BLOCK_VERSION_CONFLICT],
        review_required_blocked_count=block_reasons[BLOCK_REVIEW_REQUIRED],
        info_only_blocked_count=block_reasons[BLOCK_INFO_ONLY],
        invalid_relation_blocked_count=block_reasons[BLOCK_INVALID_RELATION],
        forbidden_relation_blocked_count=block_reasons[BLOCK_FORBIDDEN_RELATION],
        dangling_relationship_blocked_count=block_reasons[BLOCK_DANGLING_RELATION],
        issues=[] if alignment.pass_status == "PASS" else [_issue("SIDECAR_ALIGNMENT_FAILED")],
        risks=[],
    )


def _entity_blockers(entity: KgEntity, registry: DomainRegistry) -> list[str]:
    metadata = dict(entity.metadata)
    blockers = _status_blockers(metadata)
    domain = registry.normalize_domain(metadata.get("domainCode"))
    if entity.entity_type not in registry.allowed_entity_types(domain):
        blockers.append("INVALID_ENTITY_TYPE")
    if _missing_evidence(metadata):
        blockers.append(BLOCK_MISSING_EVIDENCE)
    return blockers


def _relationship_blockers(
    relationship: KgRelationship,
    registry: DomainRegistry,
) -> list[str]:
    metadata = dict(relationship.metadata)
    relation_type = str(metadata.get("relationType") or relationship.keywords)
    blockers = _status_blockers(metadata)
    domain = registry.normalize_domain(metadata.get("domainCode"))
    if relation_type.lower() in FORBIDDEN_RELATION_TYPES:
        blockers.append(BLOCK_FORBIDDEN_RELATION)
    if relation_type not in registry.allowed_relation_types(domain):
        blockers.append(BLOCK_INVALID_RELATION)
    if relation_type == "VersionConflictWith":
        blockers.append(BLOCK_VERSION_CONFLICT)
    if _missing_evidence(metadata):
        blockers.append(BLOCK_MISSING_EVIDENCE)
    return blockers


def _status_blockers(metadata: dict[str, Any]) -> list[str]:
    tokens = {
        str(metadata.get("knowledgeStatus") or ""),
        str(metadata.get("validationStatus") or ""),
        str(metadata.get("reviewDecision") or ""),
        str(metadata.get("reasonCode") or ""),
        str(metadata.get("relationType") or ""),
    }
    blockers: list[str] = []
    if "ReviewRequired" in tokens or "REVIEW_REQUIRED" in tokens:
        blockers.append(BLOCK_REVIEW_REQUIRED)
    if "InfoOnly" in tokens or "INFO_ONLY" in tokens:
        blockers.append(BLOCK_INFO_ONLY)
    if "VersionReviewRequired" in tokens or metadata.get("requiresHumanReview") is True:
        blockers.append(BLOCK_VERSION_REVIEW_REQUIRED)
    if "MISSING_EVIDENCE" in tokens or "MissingEvidence" in tokens:
        blockers.append(BLOCK_MISSING_EVIDENCE)
    if "INVALID_RELATION" in tokens or "InvalidRelation" in tokens:
        blockers.append(BLOCK_INVALID_RELATION)
    return blockers


def _missing_evidence(metadata: dict[str, Any]) -> bool:
    has_source = metadata.get("sourceUsId") or metadata.get("source_id")
    has_unit = metadata.get("textUnitId") or metadata.get("sourceTextUnitId") or metadata.get("source_id")
    has_span_or_hash = metadata.get("sourceSpan") or metadata.get("textHash")
    return not (has_source and has_unit and has_span_or_hash and metadata.get("evidenceText"))


def _enrich_sidecar_records(
    records: list[KgMetadataSidecarRecord],
    *,
    idempotency_by_key: dict[str, str],
    namespace: str,
) -> list[KgMetadataSidecarRecord]:
    enriched: list[KgMetadataSidecarRecord] = []
    for record in records:
        idempotency_key = idempotency_by_key.get(record.external_key) or _stable_key(
            namespace,
            record.external_key,
        )
        metadata = {
            **record.metadata,
            "idempotencyKey": idempotency_key,
            "rollbackKey": record.external_key,
            "testGraphApproval": "PolicyApprovedForTestGraph",
        }
        enriched.append(replace(record, metadata=metadata))
    return enriched


def _dangling_custom_kg_count(custom_kg: dict[str, list[dict[str, Any]]]) -> int:
    entity_names = {item["entity_name"] for item in custom_kg.get("entities", [])}
    return sum(
        1
        for item in custom_kg.get("relationships", [])
        if item.get("src_id") not in entity_names or item.get("tgt_id") not in entity_names
    )


def _forbidden_count(custom_kg: dict[str, list[dict[str, Any]]]) -> int:
    return sum(
        1
        for item in custom_kg.get("relationships", [])
        if str(item.get("keywords", "")).lower() in FORBIDDEN_RELATION_TYPES
    )


def _duplicate_count(values: list[str]) -> int:
    seen: set[str] = set()
    duplicate_count = 0
    for value in values:
        if value in seen:
            duplicate_count += 1
        seen.add(value)
    return duplicate_count


def _rollback_plan_present(
    custom_kg: dict[str, list[dict[str, Any]]],
    rollback_keys: list[str],
) -> bool:
    object_count = (
        len(custom_kg.get("entities", []))
        + len(custom_kg.get("relationships", []))
    )
    if object_count == 0:
        return True
    return len(rollback_keys) >= object_count


def _stable_key(*parts: str) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _issue(code: str) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": code}


__all__ = [
    "PreparedIngestionPayload",
    "prepare_policy_approved_ingestion_payload",
]
