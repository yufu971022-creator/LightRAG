from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EntityTypeCandidateSource = Literal[
    "EXPLICIT_DSL",
    "CONFIRMED_CONFIG",
    "STRUCTURAL_PARSER",
    "RELATION_SIGNATURE",
    "SECTION_DOMAIN_HEURISTIC",
    "GENERIC_NER",
    "MODEL_CANDIDATE",
]
EntityTypeResolutionDecisionType = Literal[
    "EXPLICIT_ACCEPTED",
    "CONFIG_RESOLVED",
    "STRUCTURE_RESOLVED",
    "RELATION_RESOLVED",
    "HEURISTIC_RESOLVED",
    "CANDIDATE_REVIEW",
    "CONFLICT",
    "BLOCKED_GENERIC_TYPE",
    "NO_SAFE_TYPE",
]


@dataclass(frozen=True)
class EntityTypeResolutionContext:
    document_type: str | None = None
    module_code: str | None = None
    primary_domain: str | None = None
    related_domains: list[str] = field(default_factory=list)
    feature_key: str | None = None
    section_type: str | None = None
    parent_object_type: str | None = None
    relation_role: str | None = None
    relation_type: str | None = None
    table_context: str | None = None
    field_context: str | None = None
    heading_context: str | None = None
    neighbor_terms: list[str] = field(default_factory=list)
    original_entity_name: str = ""
    original_entity_type: str | None = None
    canonical_term: str | None = None
    source_us_id: str | None = None
    text_unit_id: str | None = None
    source_span: dict[str, int] = field(default_factory=dict)
    evidence_text: str = ""
    explicit_dsl_type: str | None = None
    confirmed_config_type: str | None = None
    structural_type: str | None = None
    relation_signature_type: str | None = None


@dataclass(frozen=True)
class EntityTypeCandidate:
    candidate_type: str
    score: float
    source: EntityTypeCandidateSource
    reason_codes: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityTypeResolutionDecision:
    original_entity_type: str | None
    resolved_entity_type: str | None
    decision: EntityTypeResolutionDecisionType
    confidence: float
    candidate_types: list[EntityTypeCandidate]
    selected_type: str | None = None
    conflict_types: list[str] = field(default_factory=list)
    requires_review: bool = False
    blocked_from_pfss: bool = False
    reason_codes: list[str] = field(default_factory=list)
    signals_used: list[str] = field(default_factory=list)
    signals_rejected: list[str] = field(default_factory=list)
    identity_rekey_required: bool = False
    old_semantic_object_id: str | None = None
    new_semantic_object_id: str | None = None


@dataclass(frozen=True)
class EntityTypeResolutionEvent:
    resolution_event_id: str
    semantic_object_id: str | None
    document_version_id: str
    text_unit_id: str | None
    original_entity_name: str
    original_entity_type: str | None
    resolved_entity_type: str | None
    decision: str
    confidence: float
    candidate_types: list[dict[str, Any]]
    reason_codes: list[str]
    requires_review: bool
    old_semantic_object_id: str | None
    new_semantic_object_id: str | None
    created_at: str


@dataclass(frozen=True)
class EntityTypeMigrationPlan:
    old_semantic_object_id: str
    new_semantic_object_id: str
    old_type: str
    new_type: str
    affected_relation_ids: list[str]
    affected_evidence_mapping_ids: list[str]
    affected_version_group_keys: list[str]
    merge_target_id: str | None
    sidecar_updates: list[dict[str, Any]]
    pfss_delete_plan: list[dict[str, Any]]
    pfss_upsert_plan: list[dict[str, Any]]
    entity_vector_rebuild_required: bool
    relation_vector_rebuild_required: bool
    document_versions_affected: list[str]
    risk_level: str


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
