from __future__ import annotations

import json

from lightrag_ext.us_dsl.confirmed_graph_plan import (
    build_confirmed_graph_write_plan,
    serialize_confirmed_graph_write_plan,
)
from lightrag_ext.us_dsl.kg_metadata_sidecar import build_metadata_sidecar_records
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship
from lightrag_ext.us_dsl.promotion_gate import build_promotion_candidates
from lightrag_ext.us_dsl.promotion_manifest import promotion_manifest_from_dict
from lightrag_ext.us_dsl.promotion_types import (
    EVENT_GRAPH_WRITE_PLANNED,
    EVENT_PROMOTION_EVALUATED,
    TARGET_FORMAL_GRAPH,
)


def test_approved_candidate_with_evidence_can_enter_test_plan():
    candidates = _candidates()
    approved = _approvable_candidate_ids(candidates)[:2]

    plan = build_confirmed_graph_write_plan(
        candidates,
        manifest=_manifest(approved),
        target_namespace="dsl_test_confirmed_plan",
    )

    assert len(plan.confirmed_entities) >= 1
    assert plan.production_write is False
    assert plan.dry_run is True
    assert all(item.graph_write_status == "PLANNED" for item in plan.confirmed_entities)


def test_rollback_plan_generated():
    plan = _approved_plan()

    assert plan.rollback_plan is not None
    assert plan.rollback_plan.reversible is True
    assert plan.rollback_plan.keys_to_delete


def test_audit_events_generated():
    plan = _approved_plan()
    event_types = {item.event_type for item in plan.audit_events}

    assert EVENT_PROMOTION_EVALUATED in event_types
    assert EVENT_GRAPH_WRITE_PLANNED in event_types


def test_candidate_as_confirmed_never_auto():
    candidates = _candidates()

    plan = build_confirmed_graph_write_plan(
        candidates,
        manifest=None,
        target_namespace="dsl_test_confirmed_plan",
    )

    assert not plan.confirmed_entities
    assert not plan.confirmed_relationships
    assert plan.summary["needs_review_count"] > 0


def test_formal_graph_disabled_by_default():
    plan = build_confirmed_graph_write_plan(
        _candidates(),
        manifest=_manifest([]),
        target_namespace="dsl_test_confirmed_plan",
        target_graph_type=TARGET_FORMAL_GRAPH,
    )

    assert plan.production_write is True
    assert any("Formal graph target is disabled" in risk for risk in plan.risks)


def test_version_uncertain_case_remains_needs_review():
    payload = _payload(
        relationships=[
            KgRelationship(
                src_id="Field A",
                tgt_id="RuleVersion:1",
                description="Field A has uncertain version evidence.",
                keywords="HasVersion",
                source_id="tu-1",
                metadata=_metadata(
                    "rel-version",
                    relationType="HasVersion",
                    reviewDecision="VERSION_REVIEW",
                    versionStatus="Unknown",
                    requiresHumanReview=True,
                    reasonCode="HAS_VERSION_FROM_SEMANTIC_OBJECT",
                ),
            )
        ]
    )
    candidates = _candidates(payload=payload)
    version_candidate = [
        item for item in candidates if item.proposed_relation_type == "HasVersion"
    ][0]

    assert version_candidate.eligibility_status == "BLOCKED"
    assert "VERSION_REVIEW_REQUIRED_BLOCKED" in version_candidate.blocking_reasons


def test_confirmed_graph_plan_serializable():
    plan = _approved_plan()

    json.dumps(serialize_confirmed_graph_write_plan(plan))


def _approved_plan():
    candidates = _candidates()
    return build_confirmed_graph_write_plan(
        candidates,
        manifest=_manifest(_approvable_candidate_ids(candidates)[:3]),
        target_namespace="dsl_test_confirmed_plan",
    )


def _approvable_candidate_ids(candidates: list) -> list[str]:
    return [item.candidate_id for item in candidates if item.eligibility_status == "ELIGIBLE"]


def _candidates(payload: DslKgPayload | None = None):
    payload = payload or _payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_confirmed_plan")
    return build_promotion_candidates(kg_payload=payload, sidecar_records=records)


def _payload(relationships: list[KgRelationship] | None = None) -> DslKgPayload:
    return DslKgPayload(
        chunks=[KgChunk(content="Field A depends on Field B.", source_id="tu-1", metadata=_metadata("chunk"))],
        entities=[
            KgEntity(
                entity_name="Field A",
                entity_type="FieldSpec",
                description="Field A depends on Field B.",
                source_id="tu-1",
                metadata=_metadata("ent-a"),
            ),
            KgEntity(
                entity_name="Field B",
                entity_type="FieldSpec",
                description="Field B supports Field A.",
                source_id="tu-1",
                metadata=_metadata("ent-b"),
            ),
        ],
        relationships=relationships
        if relationships is not None
        else [
            KgRelationship(
                src_id="Field A",
                tgt_id="Field B",
                description="Field A depends on Field B.",
                keywords="DependsOn",
                source_id="tu-1",
                metadata=_metadata("rel-ab", relationType="DependsOn"),
            )
        ],
    )


def _metadata(candidate_id: str, **overrides) -> dict:
    metadata = {
        "documentId": "DOC-1",
        "sourceUsId": "US-001",
        "textUnitId": "tu-1",
        "sourceSpan": {"start": 0, "end": 10},
        "textHash": f"hash-{candidate_id}",
        "evidenceText": "Field A depends on Field B.",
        "featureKey": "FeatureA",
        "domainCode": "DomainA",
        "sectionType": "business_rule",
        "knowledgeStatus": "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": "AUTO_ACCEPT_FOR_REPORT",
        "confidenceScore": 0.91,
        "candidateId": candidate_id,
    }
    metadata.update(overrides)
    return metadata


def _manifest(candidate_ids: list[str]):
    return promotion_manifest_from_dict(
        {
            "manifest_id": "MANIFEST-1",
            "module_name": "module-a",
            "reviewer": "Reviewer",
            "decisions": [
                {
                    "candidate_id": candidate_id,
                    "decision": "APPROVED",
                    "reviewer": "Reviewer",
                    "reviewer_role": "BA",
                    "decision_reason": "Checked.",
                    "evidence_checked": True,
                    "version_checked": True,
                    "term_checked": True,
                }
                for candidate_id in candidate_ids
            ],
        }
    )
