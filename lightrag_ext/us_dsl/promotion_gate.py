from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import Any

from .kg_metadata_sidecar import (
    OBJECT_KIND_ENTITY as SIDECAR_ENTITY,
    OBJECT_KIND_RELATIONSHIP as SIDECAR_RELATIONSHIP,
    KgMetadataSidecarRecord,
    build_metadata_sidecar_records,
)
from .kg_payload_types import DslKgPayload, KgEntity, KgRelationship
from .promotion_manifest import (
    decision_blocks_formal_promotion,
    decisions_by_candidate_id,
)
from .promotion_policy import PromotionPolicy, evaluate_candidate_against_policy
from .promotion_types import (
    BLOCKED,
    DECISION_APPROVED,
    DECISION_REJECTED,
    ELIGIBLE,
    EVENT_GRAPH_WRITE_PLANNED,
    EVENT_PROMOTION_APPROVED,
    EVENT_PROMOTION_EVALUATED,
    EVENT_PROMOTION_REJECTED,
    EVENT_ROLLBACK_PLANNED,
    GRAPH_STATUS_PLANNED,
    NEEDS_REVIEW,
    OBJECT_KIND_ENTITY,
    OBJECT_KIND_RELATIONSHIP,
    OBJECT_KIND_VERSION_RELATION,
    ROLLBACK_DELETE_BY_ID,
    TARGET_FORMAL_GRAPH,
    TARGET_TEST_GRAPH,
    AuditEvent,
    ConfirmedGraphObject,
    ConfirmedGraphWritePlan,
    PromotionCandidate,
    PromotionManifest,
    RollbackPlan,
    serialize_confirmed_graph_write_plan,
)
from .version_relation_types import (
    REL_DEFINES_VERSION,
    REL_DERIVED_FROM_VERSION_EVIDENCE,
    REL_HAS_VERSION,
    REL_SUPERSEDES,
    REL_VERSION_CONFLICT,
    REL_VERSION_REVIEW_REQUIRED,
)


VERSION_RELATION_TYPES = {
    REL_HAS_VERSION,
    REL_SUPERSEDES,
    REL_VERSION_CONFLICT,
    REL_VERSION_REVIEW_REQUIRED,
    REL_DEFINES_VERSION,
    REL_DERIVED_FROM_VERSION_EVIDENCE,
}

STABLE_TIMESTAMP = "1970-01-01T00:00:00+00:00"


def build_promotion_candidates(
    *,
    kg_payload: DslKgPayload,
    sidecar_records: list[KgMetadataSidecarRecord],
    candidate_review_report: Any = None,
    version_coverage_report: Any = None,
    policy: PromotionPolicy | None = None,
) -> list[PromotionCandidate]:
    policy = policy or PromotionPolicy()
    entities_by_external_key = _entities_by_external_key(kg_payload)
    relationships_by_external_key = _relationships_by_external_key(kg_payload)
    candidates: list[PromotionCandidate] = []

    for record in sidecar_records:
        if record.object_kind == SIDECAR_ENTITY:
            entity = entities_by_external_key.get(record.external_key)
            if entity is None:
                continue
            candidates.append(
                evaluate_promotion_eligibility(
                    _candidate_from_entity(entity, record),
                    policy=policy,
                )
            )
        elif record.object_kind == SIDECAR_RELATIONSHIP:
            relationship = relationships_by_external_key.get(record.external_key)
            if relationship is None:
                continue
            candidates.append(
                evaluate_promotion_eligibility(
                    _candidate_from_relationship(relationship, record),
                    policy=policy,
                )
            )

    return _apply_endpoint_eligibility(candidates)


def evaluate_promotion_eligibility(
    candidate: PromotionCandidate,
    *,
    policy: PromotionPolicy,
) -> PromotionCandidate:
    status, reasons, reviewer_action = evaluate_candidate_against_policy(candidate, policy=policy)
    return replace(
        candidate,
        eligibility_status=status,
        blocking_reasons=reasons,
        required_reviewer_action=reviewer_action,
    )


def apply_promotion_manifest(
    candidates: list[PromotionCandidate],
    manifest: PromotionManifest,
) -> list[PromotionCandidate]:
    decisions = decisions_by_candidate_id(manifest)
    updated: list[PromotionCandidate] = []
    for candidate in candidates:
        decision = decisions.get(candidate.candidate_id)
        metadata = dict(candidate.source_object.get("metadata") or {})
        manifest_reasons = decision_blocks_formal_promotion(decision, metadata)
        if candidate.eligibility_status == BLOCKED:
            updated.append(candidate)
            continue
        if manifest_reasons:
            status = BLOCKED if decision is not None and decision.decision == DECISION_REJECTED else NEEDS_REVIEW
            updated.append(
                replace(
                    candidate,
                    eligibility_status=status,
                    blocking_reasons=_dedupe([*candidate.blocking_reasons, *manifest_reasons]),
                    required_reviewer_action="REVIEWER_APPROVAL_REQUIRED",
                )
            )
            continue
        updated.append(
            replace(
                candidate,
                eligibility_status=ELIGIBLE,
                blocking_reasons=[],
                required_reviewer_action=None,
                audit_metadata={
                    **candidate.audit_metadata,
                    "manifestId": manifest.manifest_id,
                    "promotionId": decision.promotion_id if decision else None,
                    "reviewer": decision.reviewer if decision else manifest.reviewer,
                    "reviewerRole": decision.reviewer_role if decision else None,
                    "decisionReason": decision.decision_reason if decision else None,
                    "evidenceChecked": decision.evidence_checked if decision else None,
                    "versionChecked": decision.version_checked if decision else None,
                    "termChecked": decision.term_checked if decision else None,
                },
            )
        )
    return updated


def build_confirmed_graph_write_plan(
    candidates: list[PromotionCandidate],
    *,
    manifest: PromotionManifest | None = None,
    target_namespace: str,
    dry_run: bool = True,
    target_graph_type: str = TARGET_TEST_GRAPH,
) -> ConfirmedGraphWritePlan:
    candidates_for_plan = (
        apply_promotion_manifest(candidates, manifest) if manifest is not None else _mark_missing_manifest(candidates)
    )
    module_name = manifest.module_name if manifest is not None else "unknown"
    production_write = _is_production_target(target_namespace, target_graph_type)
    confirmed = [_confirmed_object(candidate) for candidate in candidates_for_plan if candidate.eligibility_status == ELIGIBLE]
    confirmed_entities = [item for item in confirmed if item.object_kind == OBJECT_KIND_ENTITY]
    confirmed_relationships = [item for item in confirmed if item.object_kind == OBJECT_KIND_RELATIONSHIP]
    confirmed_version_relations = [
        item for item in confirmed if item.object_kind == OBJECT_KIND_VERSION_RELATION
    ]
    blocked_items = [item for item in candidates_for_plan if item.eligibility_status == BLOCKED]
    needs_review_items = [
        item for item in candidates_for_plan if item.eligibility_status == NEEDS_REVIEW
    ]
    idempotency_keys = [item.idempotency_key for item in confirmed if item.idempotency_key]
    plan_id = _stable_id("promotion-plan", module_name, target_namespace, target_graph_type, idempotency_keys)
    rollback_plan = _rollback_plan(plan_id, target_namespace, confirmed)
    audit_events = _audit_events(candidates_for_plan, confirmed, rollback_plan, manifest=manifest)
    risks: list[str] = []
    if production_write:
        risks.append("Production namespace requested; governance must block execution.")
    if target_graph_type == TARGET_FORMAL_GRAPH:
        risks.append("Formal graph target is disabled by default.")
    return ConfirmedGraphWritePlan(
        plan_id=plan_id,
        module_name=module_name,
        target_namespace=target_namespace,
        target_graph_type=target_graph_type,
        dry_run=dry_run,
        production_write=production_write,
        confirmed_entities=confirmed_entities,
        confirmed_relationships=confirmed_relationships,
        confirmed_version_relations=confirmed_version_relations,
        blocked_items=blocked_items,
        needs_review_items=needs_review_items,
        idempotency_keys=[key for key in idempotency_keys if key],
        rollback_plan=rollback_plan,
        audit_events=audit_events,
        summary=_plan_summary(candidates_for_plan, confirmed),
        risks=risks,
        recommended_next_step=_recommended_next_step(production_write, blocked_items, needs_review_items),
    )


def build_lc_promotion_plan_example(*, dry_run: bool = True) -> ConfirmedGraphWritePlan:
    from .lc_mini_graph_smoke import LcMiniGraphSmokeConfig, build_lc_mini_kg_payload
    from .promotion_manifest import promotion_manifest_from_dict

    payload = build_lc_mini_kg_payload(
        LcMiniGraphSmokeConfig(max_chunks=15, max_entities=30, max_relationships=20)
    )
    sidecar_records = build_metadata_sidecar_records(payload, namespace="dsl_test_lc_promotion")
    candidates = build_promotion_candidates(
        kg_payload=payload,
        sidecar_records=sidecar_records,
    )
    eligible_entities = [
        item
        for item in candidates
        if item.eligibility_status == ELIGIBLE
        and item.object_kind == OBJECT_KIND_ENTITY
    ][:2]
    eligible_relationships = [
        item
        for item in candidates
        if item.eligibility_status == ELIGIBLE
        and item.object_kind == OBJECT_KIND_RELATIONSHIP
    ][:1]
    approvable = [*eligible_entities, *eligible_relationships]
    manifest = promotion_manifest_from_dict(
        {
            "manifest_id": "MANIFEST-LC-PROMOTION-EXAMPLE",
            "module_name": "module_example",
            "source_document": "source_document",
            "reviewer": "BA_REVIEWER",
            "decisions": [
                {
                    "candidate_id": item.candidate_id,
                    "decision": DECISION_APPROVED,
                    "reviewer": "BA_REVIEWER",
                    "reviewer_role": "BA",
                    "decision_reason": "Evidence checked for test promotion plan.",
                    "evidence_checked": True,
                    "version_checked": True,
                    "term_checked": True,
                }
                for item in approvable
            ],
        }
    )
    return build_confirmed_graph_write_plan(
        candidates,
        manifest=manifest,
        target_namespace="dsl_test_lc_promotion",
        dry_run=dry_run,
        target_graph_type=TARGET_TEST_GRAPH,
    )


def _candidate_from_entity(entity: KgEntity, record: KgMetadataSidecarRecord) -> PromotionCandidate:
    metadata = dict(record.metadata)
    source_object = {
        "entity_name": entity.entity_name,
        "entity_type": entity.entity_type,
        "description": entity.description,
        "source_id": entity.source_id,
        "metadata": metadata,
        "external_key": record.external_key,
    }
    candidate_id = _candidate_id(metadata, record.external_key)
    return PromotionCandidate(
        candidate_id=candidate_id,
        object_kind=OBJECT_KIND_ENTITY,
        source_object=source_object,
        proposed_entity_name=entity.entity_name,
        proposed_entity_type=entity.entity_type,
        proposed_relation_type=None,
        src_id=None,
        tgt_id=None,
        knowledge_status=_string_or_none(metadata.get("knowledgeStatus")),
        review_decision=_string_or_none(metadata.get("reviewDecision")),
        validation_status=_string_or_none(metadata.get("validationStatus")),
        confidence_score=_float_or_none(metadata.get("confidenceScore")),
        evidence=_evidence(metadata, entity.source_id),
        version_metadata=_version_metadata(metadata),
        term_metadata=_term_metadata(metadata),
        eligibility_status=NEEDS_REVIEW,
        idempotency_key=_stable_id("promotion", record.external_key, metadata.get("textHash")),
        rollback_key=record.external_key,
        audit_metadata=_audit_metadata(record, metadata),
    )


def _candidate_from_relationship(
    relationship: KgRelationship,
    record: KgMetadataSidecarRecord,
) -> PromotionCandidate:
    metadata = dict(record.metadata)
    relation_type = str(metadata.get("relationType") or relationship.keywords)
    object_kind = (
        OBJECT_KIND_VERSION_RELATION
        if relation_type in VERSION_RELATION_TYPES
        else OBJECT_KIND_RELATIONSHIP
    )
    source_object = {
        "src_id": relationship.src_id,
        "tgt_id": relationship.tgt_id,
        "description": relationship.description,
        "keywords": relationship.keywords,
        "source_id": relationship.source_id,
        "weight": relationship.weight,
        "metadata": metadata,
        "external_key": record.external_key,
    }
    candidate_id = _candidate_id(metadata, record.external_key)
    return PromotionCandidate(
        candidate_id=candidate_id,
        object_kind=object_kind,
        source_object=source_object,
        proposed_entity_name=None,
        proposed_entity_type=None,
        proposed_relation_type=relation_type,
        src_id=relationship.src_id,
        tgt_id=relationship.tgt_id,
        knowledge_status=_string_or_none(metadata.get("knowledgeStatus")),
        review_decision=_string_or_none(metadata.get("reviewDecision")),
        validation_status=_string_or_none(metadata.get("validationStatus")),
        confidence_score=_float_or_none(metadata.get("confidenceScore")),
        evidence=_evidence(metadata, relationship.source_id),
        version_metadata=_version_metadata(metadata),
        term_metadata=_term_metadata(metadata),
        eligibility_status=NEEDS_REVIEW,
        idempotency_key=_stable_id("promotion", record.external_key, metadata.get("textHash")),
        rollback_key=record.external_key,
        audit_metadata=_audit_metadata(record, metadata),
    )


def _apply_endpoint_eligibility(candidates: list[PromotionCandidate]) -> list[PromotionCandidate]:
    eligible_entities = {
        item.proposed_entity_name
        for item in candidates
        if item.object_kind == OBJECT_KIND_ENTITY and item.eligibility_status == ELIGIBLE
    }
    updated: list[PromotionCandidate] = []
    for candidate in candidates:
        if candidate.object_kind not in {OBJECT_KIND_RELATIONSHIP, OBJECT_KIND_VERSION_RELATION}:
            updated.append(candidate)
            continue
        if candidate.object_kind == OBJECT_KIND_VERSION_RELATION:
            updated.append(candidate)
            continue
        missing = [
            endpoint
            for endpoint in (candidate.src_id, candidate.tgt_id)
            if endpoint not in eligible_entities
        ]
        if missing and candidate.eligibility_status == ELIGIBLE:
            updated.append(
                replace(
                    candidate,
                    eligibility_status=BLOCKED,
                    blocking_reasons=[*candidate.blocking_reasons, "RELATION_ENDPOINT_NOT_ELIGIBLE"],
                    required_reviewer_action="FIX_BLOCKERS_BEFORE_REVIEW",
                )
            )
        else:
            updated.append(candidate)
    return updated


def _mark_missing_manifest(candidates: list[PromotionCandidate]) -> list[PromotionCandidate]:
    updated: list[PromotionCandidate] = []
    for candidate in candidates:
        if candidate.eligibility_status == ELIGIBLE:
            updated.append(
                replace(
                    candidate,
                    eligibility_status=NEEDS_REVIEW,
                    blocking_reasons=["MISSING_MANIFEST_DECISION"],
                    required_reviewer_action="REVIEWER_APPROVAL_REQUIRED",
                )
            )
        else:
            updated.append(candidate)
    return updated


def _confirmed_object(candidate: PromotionCandidate) -> ConfirmedGraphObject:
    source_object = candidate.source_object
    return ConfirmedGraphObject(
        confirmed_id=_stable_id("confirmed", candidate.idempotency_key),
        object_kind=candidate.object_kind,
        entity_name=candidate.proposed_entity_name,
        entity_type=candidate.proposed_entity_type,
        src_id=candidate.src_id,
        tgt_id=candidate.tgt_id,
        relation_type=candidate.proposed_relation_type,
        description=_string_or_none(source_object.get("description")),
        source_id=_string_or_none(source_object.get("source_id")),
        evidence=dict(candidate.evidence),
        version_metadata=dict(candidate.version_metadata),
        term_metadata=dict(candidate.term_metadata),
        idempotency_key=str(candidate.idempotency_key),
        rollback_key=str(candidate.rollback_key),
        audit_metadata=dict(candidate.audit_metadata),
        graph_write_status=GRAPH_STATUS_PLANNED,
    )


def _rollback_plan(
    plan_id: str,
    namespace: str,
    objects: list[ConfirmedGraphObject],
) -> RollbackPlan:
    return RollbackPlan(
        rollback_id=_stable_id("rollback", plan_id, namespace),
        plan_id=plan_id,
        namespace=namespace,
        keys_to_delete=[item.idempotency_key for item in objects],
        edges_to_delete=[
            item.rollback_key
            for item in objects
            if item.object_kind in {OBJECT_KIND_RELATIONSHIP, OBJECT_KIND_VERSION_RELATION}
        ],
        nodes_to_delete=[
            item.rollback_key for item in objects if item.object_kind == OBJECT_KIND_ENTITY
        ],
        sidecar_records_to_delete=[item.rollback_key for item in objects],
        reversible=True,
        rollback_strategy=ROLLBACK_DELETE_BY_ID,
        risks=[],
    )


def _audit_events(
    candidates: list[PromotionCandidate],
    confirmed: list[ConfirmedGraphObject],
    rollback_plan: RollbackPlan,
    *,
    manifest: PromotionManifest | None,
) -> list[AuditEvent]:
    events: list[AuditEvent] = []
    actor = manifest.reviewer if manifest is not None and manifest.reviewer else "SYSTEM"
    for candidate in candidates:
        events.append(
            _event(
                EVENT_PROMOTION_EVALUATED,
                candidate.candidate_id,
                actor,
                {
                    "eligibilityStatus": candidate.eligibility_status,
                    "blockingReasons": list(candidate.blocking_reasons),
                },
            )
        )
        if candidate.eligibility_status == ELIGIBLE:
            events.append(_event(EVENT_PROMOTION_APPROVED, candidate.candidate_id, actor, {}))
        elif candidate.eligibility_status == BLOCKED:
            events.append(
                _event(
                    EVENT_PROMOTION_REJECTED,
                    candidate.candidate_id,
                    actor,
                    {"blockingReasons": list(candidate.blocking_reasons)},
                )
            )
    for item in confirmed:
        events.append(_event(EVENT_GRAPH_WRITE_PLANNED, item.confirmed_id, actor, {}))
    events.append(_event(EVENT_ROLLBACK_PLANNED, rollback_plan.rollback_id, actor, {}))
    return events


def _event(
    event_type: str,
    object_id: str | None,
    actor: str,
    metadata: dict[str, Any],
) -> AuditEvent:
    return AuditEvent(
        event_id=_stable_id("audit", event_type, object_id, metadata),
        event_type=event_type,
        object_id=object_id,
        actor=actor,
        timestamp=STABLE_TIMESTAMP,
        metadata=metadata,
    )


def _plan_summary(
    candidates: list[PromotionCandidate],
    confirmed: list[ConfirmedGraphObject],
) -> dict[str, Any]:
    return {
        "candidate_count": len(candidates),
        "eligible_count": sum(1 for item in candidates if item.eligibility_status == ELIGIBLE),
        "approved_count": len(confirmed),
        "blocked_count": sum(1 for item in candidates if item.eligibility_status == BLOCKED),
        "needs_review_count": sum(1 for item in candidates if item.eligibility_status == NEEDS_REVIEW),
        "confirmed_object_count": len(confirmed),
        "confirmed_entity_count": sum(1 for item in confirmed if item.object_kind == OBJECT_KIND_ENTITY),
        "confirmed_relationship_count": sum(
            1 for item in confirmed if item.object_kind == OBJECT_KIND_RELATIONSHIP
        ),
        "confirmed_version_relation_count": sum(
            1 for item in confirmed if item.object_kind == OBJECT_KIND_VERSION_RELATION
        ),
        "version_blocked_count": _blocked_count(candidates, "VERSION"),
        "missing_evidence_blocked_count": _blocked_count(candidates, "MISSING_EVIDENCE"),
        "invalid_relation_blocked_count": _blocked_count(candidates, "INVALID_RELATION"),
    }


def _recommended_next_step(
    production_write: bool,
    blocked_items: list[PromotionCandidate],
    needs_review_items: list[PromotionCandidate],
) -> str:
    if production_write:
        return "DO_NOT_WRITE_PRODUCTION_GRAPH"
    if blocked_items:
        return "FIX_PROMOTION_BLOCKERS"
    if needs_review_items:
        return "COLLECT_REVIEWER_MANIFEST"
    return "READY_FOR_TEST_NAMESPACE_CONFIRMED_GRAPH_DRY_RUN"


def _entities_by_external_key(payload: DslKgPayload) -> dict[str, KgEntity]:
    from .kg_metadata_sidecar import entity_external_key

    return {
        entity_external_key(entity.entity_type, entity.entity_name, entity.source_id): entity
        for entity in payload.entities
    }


def _relationships_by_external_key(payload: DslKgPayload) -> dict[str, KgRelationship]:
    from .kg_metadata_sidecar import relationship_external_key

    values: dict[str, KgRelationship] = {}
    for relationship in payload.relationships:
        relation_type = str(relationship.metadata.get("relationType") or relationship.keywords)
        values[
            relationship_external_key(
                relationship.src_id,
                relationship.tgt_id,
                relation_type,
                relationship.source_id,
            )
        ] = relationship
    return values


def _evidence(metadata: dict[str, Any], source_id: str | None) -> dict[str, Any]:
    return {
        "sourceUsId": metadata.get("sourceUsId"),
        "textUnitId": metadata.get("textUnitId") or metadata.get("sourceTextUnitId"),
        "source_id": source_id,
        "sourceSpan": metadata.get("sourceSpan"),
        "textHash": metadata.get("textHash"),
        "evidenceText": metadata.get("evidenceText"),
    }


def _version_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "versionGroupKey",
        "version_group_key",
        "ruleVersion",
        "latestFlag",
        "versionStatus",
        "supersedes",
        "requiresHumanReview",
        "reasonCode",
        "safeToAutoAccept",
        "supersededVersion",
    )
    return {key: metadata.get(key) for key in keys if key in metadata}


def _term_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "originalTerm",
        "canonicalTerm",
        "termReviewRequired",
        "termAmbiguity",
        "canonicalTermReviewRequired",
    )
    return {key: metadata.get(key) for key in keys if key in metadata}


def _audit_metadata(record: KgMetadataSidecarRecord, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "sidecarId": record.sidecar_id,
        "externalKey": record.external_key,
        "metadataHash": record.metadata_hash,
        "payloadHash": record.payload_hash,
        "candidateId": metadata.get("candidateId"),
        "documentId": metadata.get("documentId"),
        "sourceUsId": metadata.get("sourceUsId"),
        "textUnitId": metadata.get("textUnitId"),
        "featureKey": metadata.get("featureKey"),
        "domainCode": metadata.get("domainCode"),
        "sectionType": metadata.get("sectionType"),
    }


def _candidate_id(metadata: dict[str, Any], external_key: str) -> str:
    return str(metadata.get("candidateId") or _stable_id("candidate", external_key))


def _blocked_count(candidates: list[PromotionCandidate], token: str) -> int:
    return sum(
        1
        for item in candidates
        if item.eligibility_status == BLOCKED
        and any(token in reason for reason in item.blocking_reasons)
    )


def _is_production_target(namespace: str, target_graph_type: str) -> bool:
    lowered = namespace.lower()
    return "test" not in lowered and "dsl_test" not in lowered or target_graph_type == TARGET_FORMAL_GRAPH


def _stable_id(*parts: Any) -> str:
    payload = "|".join(_jsonable(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _jsonable(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


__all__ = [
    "VERSION_RELATION_TYPES",
    "apply_promotion_manifest",
    "build_confirmed_graph_write_plan",
    "build_lc_promotion_plan_example",
    "build_promotion_candidates",
    "evaluate_promotion_eligibility",
    "serialize_confirmed_graph_write_plan",
]
