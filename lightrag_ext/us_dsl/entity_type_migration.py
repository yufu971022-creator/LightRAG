from __future__ import annotations

from typing import Any

from .entity_type_resolution_types import EntityTypeMigrationPlan, EntityTypeResolutionDecision
from .semantic_identity import build_semantic_identity_key, stable_semantic_object_id, stable_semantic_relation_id, stable_version_group_key
from .term_normalization_types import TermNormalizationDecision, TermScope


def build_type_migration_plan(
    *,
    original_object: dict[str, Any],
    decision: EntityTypeResolutionDecision,
    canonical_key: str,
    scope: TermScope,
    relations: list[dict[str, Any]],
    evidence_mapping_ids: list[str],
    existing_target_identity: bool = False,
) -> EntityTypeMigrationPlan:
    old_id = str(original_object["semantic_object_id"])
    old_type = str(original_object.get("object_type") or decision.original_entity_type or "Unknown")
    new_type = str(decision.resolved_entity_type or old_type)
    term_decision = TermNormalizationDecision(
        original_term=str(original_object.get("canonical_name", canonical_key)),
        lexically_normalized_term=canonical_key,
        canonical_term=str(original_object.get("canonical_name", canonical_key)),
        canonical_key=canonical_key,
        semantic_scope_key=scope.semantic_scope_key(),
        decision="IDENTITY",
        mapping_status=None,
        mapping_source=None,
        confidence=1.0,
    )
    identity_key = build_semantic_identity_key(term_decision, scope=scope, object_type=new_type)
    new_id = stable_semantic_object_id(identity_key)
    affected_relation_ids = [str(row["relation_id"]) for row in relations]
    rekeyed_relations = [
        {
            "old_relation_id": row["relation_id"],
            "new_relation_id": stable_semantic_relation_id(
                src_semantic_object_id=new_id if row.get("src") == old_id else str(row.get("src")),
                relation_type=str(row.get("relation_type")),
                tgt_semantic_object_id=new_id if row.get("tgt") == old_id else str(row.get("tgt")),
                relation_scope=scope.feature_key,
            ),
        }
        for row in relations
    ]
    return EntityTypeMigrationPlan(
        old_semantic_object_id=old_id,
        new_semantic_object_id=new_id,
        old_type=old_type,
        new_type=new_type,
        affected_relation_ids=affected_relation_ids,
        affected_evidence_mapping_ids=list(evidence_mapping_ids),
        affected_version_group_keys=[str(original_object.get("version_group_key", "")), stable_version_group_key(identity_key)],
        merge_target_id=new_id if existing_target_identity else None,
        sidecar_updates=[{"field": "resolved_entity_type", "value": new_type}, {"field": "semantic_object_id", "from": old_id, "to": new_id}],
        pfss_delete_plan=[{"delete_node": old_id}] if old_id != new_id else [],
        pfss_upsert_plan=[{"upsert_node": new_id, "type": new_type}],
        entity_vector_rebuild_required=old_id != new_id,
        relation_vector_rebuild_required=bool(rekeyed_relations),
        document_versions_affected=sorted({str(original_object.get("document_version_id", "docver-fixture"))}),
        risk_level="MEDIUM" if existing_target_identity else "LOW",
    )
