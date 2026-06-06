from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


OBJECT_KIND_ENTITY = "entity"
OBJECT_KIND_RELATIONSHIP = "relationship"
OBJECT_KIND_VERSION_RELATION = "version_relation"

ELIGIBLE = "ELIGIBLE"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
NEEDS_REVIEW = "NEEDS_REVIEW"
BLOCKED = "BLOCKED"

DECISION_APPROVED = "APPROVED"
DECISION_REJECTED = "REJECTED"
DECISION_NEEDS_REVIEW = "NEEDS_REVIEW"
DECISION_BLOCKED = "BLOCKED"

GRAPH_STATUS_PLANNED = "PLANNED"
GRAPH_STATUS_WRITTEN = "WRITTEN"
GRAPH_STATUS_ROLLED_BACK = "ROLLED_BACK"
GRAPH_STATUS_FAILED = "FAILED"

TARGET_TEST_GRAPH = "test_graph"
TARGET_FORMAL_GRAPH = "formal_graph"

ROLLBACK_DELETE_BY_ID = "delete_by_id"
ROLLBACK_NAMESPACE_RESET = "namespace_reset"
ROLLBACK_TEMP_WORKSPACE_CLEANUP = "temp_workspace_cleanup"
ROLLBACK_MANUAL_REQUIRED = "manual_required"

EVENT_PROMOTION_EVALUATED = "PROMOTION_EVALUATED"
EVENT_PROMOTION_APPROVED = "PROMOTION_APPROVED"
EVENT_PROMOTION_REJECTED = "PROMOTION_REJECTED"
EVENT_GRAPH_WRITE_PLANNED = "GRAPH_WRITE_PLANNED"
EVENT_GRAPH_WRITE_EXECUTED = "GRAPH_WRITE_EXECUTED"
EVENT_ROLLBACK_PLANNED = "ROLLBACK_PLANNED"
EVENT_ROLLBACK_EXECUTED = "ROLLBACK_EXECUTED"


@dataclass(frozen=True)
class PromotionCandidate:
    candidate_id: str
    object_kind: str
    source_object: dict[str, Any]
    proposed_entity_name: str | None
    proposed_entity_type: str | None
    proposed_relation_type: str | None
    src_id: str | None
    tgt_id: str | None
    knowledge_status: str | None
    review_decision: str | None
    validation_status: str | None
    confidence_score: float | None
    evidence: dict[str, Any]
    version_metadata: dict[str, Any]
    term_metadata: dict[str, Any]
    eligibility_status: str
    blocking_reasons: list[str] = field(default_factory=list)
    required_reviewer_action: str | None = None
    idempotency_key: str | None = None
    rollback_key: str | None = None
    audit_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PromotionDecision:
    promotion_id: str
    candidate_id: str
    decision: str
    reviewer: str | None
    reviewer_role: str | None
    decision_reason: str
    decision_time: str | None
    evidence_checked: bool
    version_checked: bool
    term_checked: bool
    comments: str | None = None


@dataclass(frozen=True)
class PromotionManifest:
    manifest_id: str
    module_name: str
    source_document: str | None
    created_at: str | None
    reviewer: str | None
    decisions: list[PromotionDecision]
    scope: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None


@dataclass(frozen=True)
class ConfirmedGraphObject:
    confirmed_id: str
    object_kind: str
    entity_name: str | None
    entity_type: str | None
    src_id: str | None
    tgt_id: str | None
    relation_type: str | None
    description: str | None
    source_id: str | None
    evidence: dict[str, Any]
    version_metadata: dict[str, Any]
    term_metadata: dict[str, Any]
    idempotency_key: str
    rollback_key: str
    audit_metadata: dict[str, Any]
    graph_write_status: str = GRAPH_STATUS_PLANNED


@dataclass(frozen=True)
class RollbackPlan:
    rollback_id: str
    plan_id: str
    namespace: str
    keys_to_delete: list[str]
    edges_to_delete: list[str]
    nodes_to_delete: list[str]
    sidecar_records_to_delete: list[str]
    reversible: bool
    rollback_strategy: str
    risks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    event_type: str
    object_id: str | None
    actor: str
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfirmedGraphWritePlan:
    plan_id: str
    module_name: str
    target_namespace: str
    target_graph_type: str
    dry_run: bool
    production_write: bool
    confirmed_entities: list[ConfirmedGraphObject]
    confirmed_relationships: list[ConfirmedGraphObject]
    confirmed_version_relations: list[ConfirmedGraphObject]
    blocked_items: list[PromotionCandidate]
    needs_review_items: list[PromotionCandidate]
    idempotency_keys: list[str]
    rollback_plan: RollbackPlan | None
    audit_events: list[AuditEvent]
    summary: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)
    recommended_next_step: str = ""


def serialize_promotion_candidate(candidate: PromotionCandidate) -> dict[str, Any]:
    return asdict(candidate)


def serialize_promotion_manifest(manifest: PromotionManifest) -> dict[str, Any]:
    return asdict(manifest)


def serialize_confirmed_graph_write_plan(plan: ConfirmedGraphWritePlan) -> dict[str, Any]:
    return asdict(plan)


__all__ = [
    "AuditEvent",
    "BLOCKED",
    "ConfirmedGraphObject",
    "ConfirmedGraphWritePlan",
    "DECISION_APPROVED",
    "DECISION_BLOCKED",
    "DECISION_NEEDS_REVIEW",
    "DECISION_REJECTED",
    "ELIGIBLE",
    "EVENT_GRAPH_WRITE_EXECUTED",
    "EVENT_GRAPH_WRITE_PLANNED",
    "EVENT_PROMOTION_APPROVED",
    "EVENT_PROMOTION_EVALUATED",
    "EVENT_PROMOTION_REJECTED",
    "EVENT_ROLLBACK_EXECUTED",
    "EVENT_ROLLBACK_PLANNED",
    "GRAPH_STATUS_FAILED",
    "GRAPH_STATUS_PLANNED",
    "GRAPH_STATUS_ROLLED_BACK",
    "GRAPH_STATUS_WRITTEN",
    "NEEDS_REVIEW",
    "NOT_ELIGIBLE",
    "OBJECT_KIND_ENTITY",
    "OBJECT_KIND_RELATIONSHIP",
    "OBJECT_KIND_VERSION_RELATION",
    "PromotionCandidate",
    "PromotionDecision",
    "PromotionManifest",
    "ROLLBACK_DELETE_BY_ID",
    "ROLLBACK_MANUAL_REQUIRED",
    "ROLLBACK_NAMESPACE_RESET",
    "ROLLBACK_TEMP_WORKSPACE_CLEANUP",
    "RollbackPlan",
    "TARGET_FORMAL_GRAPH",
    "TARGET_TEST_GRAPH",
    "serialize_confirmed_graph_write_plan",
    "serialize_promotion_candidate",
    "serialize_promotion_manifest",
]
