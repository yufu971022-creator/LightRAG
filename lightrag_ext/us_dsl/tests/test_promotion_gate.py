from __future__ import annotations

import json

from lightrag_ext.us_dsl.kg_metadata_sidecar import build_metadata_sidecar_records
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship
from lightrag_ext.us_dsl.promotion_gate import (
    build_confirmed_graph_write_plan,
    build_promotion_candidates,
)
from lightrag_ext.us_dsl.promotion_manifest import promotion_manifest_from_dict
from lightrag_ext.us_dsl.promotion_types import BLOCKED, NEEDS_REVIEW


def test_candidate_without_manifest_not_formally_promoted():
    candidates = _promotion_candidates()

    plan = build_confirmed_graph_write_plan(
        candidates,
        manifest=None,
        target_namespace="dsl_test_promotion",
    )

    assert plan.confirmed_entities == []
    assert plan.confirmed_relationships == []
    assert any(item.eligibility_status == NEEDS_REVIEW for item in plan.needs_review_items)


def test_missing_evidence_blocks_promotion():
    candidates = _promotion_candidates(entity_metadata={"evidenceText": None})

    candidate = _candidate(candidates, "Field A")

    assert candidate.eligibility_status == BLOCKED
    assert "MISSING_EVIDENCE" in candidate.blocking_reasons


def test_review_required_blocks_promotion():
    candidates = _promotion_candidates(entity_metadata={"reviewDecision": "REVIEW_REQUIRED"})

    candidate = _candidate(candidates, "Field A")

    assert candidate.eligibility_status == BLOCKED
    assert "REVIEW_REQUIRED_BLOCKED" in candidate.blocking_reasons


def test_info_only_blocks_promotion():
    candidates = _promotion_candidates(entity_metadata={"reviewDecision": "INFO_ONLY"})

    candidate = _candidate(candidates, "Field A")

    assert candidate.eligibility_status == BLOCKED
    assert "INFO_ONLY_BLOCKED" in candidate.blocking_reasons


def test_version_review_required_blocks_promotion():
    payload = _payload(
        relationships=[
            KgRelationship(
                src_id="Field A",
                tgt_id="RuleVersion:1",
                description="Field A requires version review.",
                keywords="VersionReviewRequired",
                source_id="tu-1",
                metadata=_metadata(
                    "rel-version-review",
                    relationType="VersionReviewRequired",
                    knowledgeStatus="ReviewRequired",
                    reviewDecision="VERSION_REVIEW",
                    requiresHumanReview=True,
                    reasonCode="MISSING_EXPLICIT_VERSION_STATUS",
                ),
            )
        ]
    )

    candidate = _candidate(_promotion_candidates(payload=payload), "VersionReviewRequired")

    assert candidate.eligibility_status == BLOCKED
    assert "VERSION_REVIEW_REQUIRED_BLOCKED" in candidate.blocking_reasons


def test_supersedes_requires_explicit_evidence():
    payload = _payload(
        relationships=[
            KgRelationship(
                src_id="RuleVersion:2",
                tgt_id="RuleVersion:1",
                description="Rule version 2 supersedes version 1.",
                keywords="Supersedes",
                source_id="tu-1",
                metadata=_metadata(
                    "rel-supersedes",
                    relationType="Supersedes",
                    versionStatus="Current",
                    reviewDecision="AUTO_ACCEPT_FOR_REPORT",
                ),
            )
        ]
    )

    candidate = _candidate(_promotion_candidates(payload=payload), "Supersedes")

    assert candidate.eligibility_status == BLOCKED
    assert "SUPERSEDES_REQUIRES_EXPLICIT_EVIDENCE" in candidate.blocking_reasons


def test_invalid_relation_blocks_promotion():
    payload = _payload(
        relationships=[
            KgRelationship(
                src_id="Field A",
                tgt_id="Field B",
                description="Invalid relation.",
                keywords="has_child",
                source_id="tu-1",
                metadata=_metadata("rel-invalid", relationType="has_child"),
            )
        ]
    )

    candidate = _candidate(_promotion_candidates(payload=payload), "has_child")

    assert candidate.eligibility_status == BLOCKED
    assert "FORBIDDEN_RELATION_TYPE" in candidate.blocking_reasons


def test_manifest_cannot_override_blocker():
    candidates = _promotion_candidates(entity_metadata={"evidenceText": None})
    manifest = _manifest([_candidate(candidates, "Field A").candidate_id])

    plan = build_confirmed_graph_write_plan(
        candidates,
        manifest=manifest,
        target_namespace="dsl_test_promotion",
    )

    assert plan.confirmed_entities == []
    assert any("MISSING_EVIDENCE" in item.blocking_reasons for item in plan.blocked_items)


def test_idempotency_keys_stable():
    first = _promotion_candidates()
    second = _promotion_candidates()

    assert [item.idempotency_key for item in first] == [item.idempotency_key for item in second]


def test_plan_serializable_from_gate():
    candidates = _promotion_candidates()
    approved = [_candidate(candidates, "Field A").candidate_id]
    plan = build_confirmed_graph_write_plan(
        candidates,
        manifest=_manifest(approved),
        target_namespace="dsl_test_promotion",
    )

    json.dumps(plan.summary)


def _promotion_candidates(
    *,
    payload: DslKgPayload | None = None,
    entity_metadata: dict | None = None,
) -> list:
    payload = payload or _payload(entity_metadata=entity_metadata)
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_promotion")
    return build_promotion_candidates(kg_payload=payload, sidecar_records=records)


def _payload(
    *,
    entity_metadata: dict | None = None,
    relationships: list[KgRelationship] | None = None,
) -> DslKgPayload:
    metadata_a = _metadata("ent-a", **(entity_metadata or {}))
    metadata_b = _metadata("ent-b")
    return DslKgPayload(
        chunks=[
            KgChunk(content="Field A depends on Field B.", source_id="tu-1", metadata=metadata_a)
        ],
        entities=[
            KgEntity(
                entity_name="Field A",
                entity_type="FieldSpec",
                description="Field A depends on Field B.",
                source_id="tu-1",
                metadata=metadata_a,
            ),
            KgEntity(
                entity_name="Field B",
                entity_type="FieldSpec",
                description="Field B supports Field A.",
                source_id="tu-1",
                metadata=metadata_b,
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


def _candidate(candidates: list, value: str):
    for candidate in candidates:
        if candidate.proposed_entity_name == value or candidate.proposed_relation_type == value:
            return candidate
    raise AssertionError(value)
