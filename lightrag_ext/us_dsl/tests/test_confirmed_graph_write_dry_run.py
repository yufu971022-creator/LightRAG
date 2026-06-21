from __future__ import annotations

import json
import os

import pytest

from lightrag_ext.us_dsl.confirmed_graph_custom_kg import (
    build_confirmed_graph_sidecar_records,
    to_confirmed_custom_kg_input,
    validate_confirmed_sidecar_alignment,
)
from lightrag_ext.us_dsl.confirmed_graph_write_dry_run import (
    ENABLE_CONFIRMED_GRAPH_WRITE_DRY_RUN_ENV,
    ConfirmedGraphWriteDryRunConfig,
    run_confirmed_graph_write_dry_run,
    serialize_confirmed_graph_write_dry_run_report,
)
from lightrag_ext.us_dsl.graph_write_governance import validate_graph_write_plan
from lightrag_ext.us_dsl.kg_metadata_sidecar import build_metadata_sidecar_records
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship
from lightrag_ext.us_dsl.promotion_gate import (
    build_confirmed_graph_write_plan,
    build_lc_promotion_plan_example,
    build_promotion_candidates,
)
from lightrag_ext.us_dsl.promotion_manifest import promotion_manifest_from_dict


def test_disabled_skips_confirmed_graph_write():
    report = run_confirmed_graph_write_dry_run(
        plan=_approved_plan(),
        config=ConfirmedGraphWriteDryRunConfig(enabled=False),
    )

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_attempted is False


def test_confirmed_custom_kg_input_schema():
    plan = build_lc_promotion_plan_example(dry_run=True)
    custom_kg = to_confirmed_custom_kg_input(plan, max_entities=5, max_relationships=3)

    assert set(custom_kg) == {"chunks", "entities", "relationships"}
    assert custom_kg["chunks"]
    assert len(custom_kg["entities"]) == 2
    assert len(custom_kg["relationships"]) == 1
    chunk_source_ids = {item["source_id"] for item in custom_kg["chunks"]}
    entity_names = {item["entity_name"] for item in custom_kg["entities"]}
    assert all(item["source_id"] in chunk_source_ids for item in custom_kg["entities"])
    assert all(item["source_id"] in chunk_source_ids for item in custom_kg["relationships"])
    assert all(item["src_id"] in entity_names and item["tgt_id"] in entity_names for item in custom_kg["relationships"])
    assert "metadata" not in custom_kg["entities"][0]


def test_confirmed_sidecar_alignment():
    plan = build_lc_promotion_plan_example(dry_run=True)
    custom_kg = to_confirmed_custom_kg_input(plan)
    records = build_confirmed_graph_sidecar_records(
        plan,
        custom_kg,
        namespace=plan.target_namespace,
    )
    alignment = validate_confirmed_sidecar_alignment(custom_kg, records)

    assert len(records) == (
        len(custom_kg["chunks"]) + len(custom_kg["entities"]) + len(custom_kg["relationships"])
    )
    assert alignment.pass_status == "PASS"
    assert all(record.metadata.get("manifestId") for record in records)
    assert all(record.metadata.get("idempotencyKey") for record in records)


def test_governance_required_before_write():
    plan = _approved_plan(namespace="production")
    report = run_confirmed_graph_write_dry_run(
        plan=plan,
        config=ConfirmedGraphWriteDryRunConfig(enabled=True),
    )

    assert validate_graph_write_plan(plan).pass_status == "FAIL"
    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.recommended_next_step == "FIX_GRAPH_WRITE_GOVERNANCE"


def test_blocks_production_namespace():
    report = run_confirmed_graph_write_dry_run(
        plan=_approved_plan(namespace="production"),
        config=ConfirmedGraphWriteDryRunConfig(enabled=True),
    )

    assert report.skipped is True
    assert report.production_write is True
    assert report.ainsert_custom_kg_called is False


def test_blocks_review_required_in_confirmed_write():
    report = run_confirmed_graph_write_dry_run(
        plan=_blocked_entity_plan({"reviewDecision": "REVIEW_REQUIRED"}),
        config=ConfirmedGraphWriteDryRunConfig(enabled=True),
    )

    assert report.skipped is True
    assert report.custom_kg_entity_count == 0
    assert report.ainsert_custom_kg_called is False


def test_blocks_info_only_in_confirmed_write():
    report = run_confirmed_graph_write_dry_run(
        plan=_blocked_entity_plan({"reviewDecision": "INFO_ONLY"}),
        config=ConfirmedGraphWriteDryRunConfig(enabled=True),
    )

    assert report.skipped is True
    assert report.custom_kg_entity_count == 0


def test_blocks_version_review_required_in_confirmed_write():
    report = run_confirmed_graph_write_dry_run(
        plan=_version_review_plan(),
        config=ConfirmedGraphWriteDryRunConfig(enabled=True),
    )

    assert report.skipped is True
    assert report.custom_kg_relationship_count == 0


def test_blocks_missing_evidence_in_confirmed_write():
    report = run_confirmed_graph_write_dry_run(
        plan=_blocked_entity_plan({"evidenceText": None}),
        config=ConfirmedGraphWriteDryRunConfig(enabled=True),
    )

    assert report.skipped is True
    assert report.missing_evidence_written_count == 0


def test_blocks_invalid_relation_in_confirmed_write():
    plan = _blocked_relationship_plan("has_child")
    report = run_confirmed_graph_write_dry_run(
        plan=plan,
        config=ConfirmedGraphWriteDryRunConfig(enabled=True),
    )

    assert report.skipped is True
    assert report.custom_kg_relationship_count == 0


def test_manifest_type_test_is_marked_test_only():
    report = run_confirmed_graph_write_dry_run(
        plan=_approved_plan(),
        config=ConfirmedGraphWriteDryRunConfig(enabled=False, manifest_type="TEST_MANIFEST"),
    )

    assert report.manifest_type == "TEST_MANIFEST"
    assert report.test_only is True


def test_idempotency_keys_unique():
    report = run_confirmed_graph_write_dry_run(
        plan=_approved_plan(),
        config=ConfirmedGraphWriteDryRunConfig(enabled=False),
    )

    assert report.idempotency_key_duplicate_count == 0


def test_rollback_plan_required():
    report = run_confirmed_graph_write_dry_run(
        plan=_approved_plan(),
        config=ConfirmedGraphWriteDryRunConfig(enabled=False),
    )

    assert report.rollback_plan_present is True


def test_audit_events_required():
    report = run_confirmed_graph_write_dry_run(
        plan=_approved_plan(),
        config=ConfirmedGraphWriteDryRunConfig(enabled=False),
    )

    assert report.audit_event_count > 0


def test_default_no_real_write(monkeypatch):
    monkeypatch.delenv(ENABLE_CONFIRMED_GRAPH_WRITE_DRY_RUN_ENV, raising=False)

    report = run_confirmed_graph_write_dry_run(
        plan=_approved_plan(),
        config=ConfirmedGraphWriteDryRunConfig.from_env(),
    )

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False


def test_report_serializable():
    report = run_confirmed_graph_write_dry_run(
        plan=_approved_plan(),
        config=ConfirmedGraphWriteDryRunConfig(enabled=False),
    )

    json.dumps(serialize_confirmed_graph_write_dry_run_report(report))


def test_real_confirmed_graph_write_if_enabled():
    if os.getenv(ENABLE_CONFIRMED_GRAPH_WRITE_DRY_RUN_ENV) != "1":
        pytest.skip("Confirmed graph write dry-run is opt-in only.")

    report = run_confirmed_graph_write_dry_run(
        plan=build_lc_promotion_plan_example(dry_run=True),
        config=ConfirmedGraphWriteDryRunConfig.from_env(),
    )
    if report.skipped:
        pytest.skip(report.skip_reason or "Confirmed graph write dry-run skipped.")

    assert report.manifest_type == "TEST_MANIFEST"
    assert report.test_only is True
    assert report.governance_passed is True
    assert report.sidecar_alignment_passed is True
    assert report.ainsert_custom_kg_called is True
    assert report.graph_write_succeeded is True
    assert report.neo4j_connected is False
    assert report.production_write is False
    assert report.rollback_executed is True
    assert report.rollback_passed is True
    assert report.cleanup_passed is True


def _approved_plan(namespace: str = "dsl_test_confirmed_write", relationship_type: str = "DependsOn"):
    payload = _payload(relationship_type=relationship_type)
    records = build_metadata_sidecar_records(payload, namespace=namespace)
    candidates = build_promotion_candidates(kg_payload=payload, sidecar_records=records)
    approved = [item.candidate_id for item in candidates if item.eligibility_status == "ELIGIBLE"]
    return build_confirmed_graph_write_plan(
        candidates,
        manifest=_manifest(approved),
        target_namespace=namespace,
    )


def _blocked_entity_plan(entity_metadata: dict):
    payload = DslKgPayload(
        chunks=[KgChunk(content="Field A depends on Field B.", source_id="tu-1", metadata=_metadata("chunk"))],
        entities=[
            KgEntity(
                entity_name="Field A",
                entity_type="FieldSpec",
                description="Field A depends on Field B.",
                source_id="tu-1",
                metadata=_metadata("ent-a", **entity_metadata),
            )
        ],
        relationships=[],
    )
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_confirmed_write")
    candidates = build_promotion_candidates(kg_payload=payload, sidecar_records=records)
    return build_confirmed_graph_write_plan(
        candidates,
        manifest=_manifest([item.candidate_id for item in candidates]),
        target_namespace="dsl_test_confirmed_write",
    )


def _blocked_relationship_plan(relationship_type: str):
    payload = DslKgPayload(
        chunks=[KgChunk(content="Invalid relation evidence.", source_id="tu-1", metadata=_metadata("chunk"))],
        entities=[],
        relationships=[
            KgRelationship(
                src_id="Field A",
                tgt_id="Field B",
                description="Invalid relation.",
                keywords=relationship_type,
                source_id="tu-1",
                metadata=_metadata("rel-invalid", relationType=relationship_type),
            )
        ],
    )
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_confirmed_write")
    candidates = build_promotion_candidates(kg_payload=payload, sidecar_records=records)
    return build_confirmed_graph_write_plan(
        candidates,
        manifest=_manifest([item.candidate_id for item in candidates]),
        target_namespace="dsl_test_confirmed_write",
    )


def _version_review_plan():
    payload = DslKgPayload(
        chunks=[KgChunk(content="Version review evidence.", source_id="tu-1", metadata=_metadata("chunk"))],
        entities=[],
        relationships=[
            KgRelationship(
                src_id="Field A",
                tgt_id="RuleVersion:1",
                description="Field A has uncertain version evidence.",
                keywords="VersionReviewRequired",
                source_id="tu-1",
                metadata=_metadata(
                    "rel-version",
                    relationType="VersionReviewRequired",
                    reviewDecision="VERSION_REVIEW",
                    knowledgeStatus="ReviewRequired",
                    requiresHumanReview=True,
                    reasonCode="MISSING_EXPLICIT_VERSION_STATUS",
                ),
            )
        ]
    )
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_confirmed_write")
    candidates = build_promotion_candidates(kg_payload=payload, sidecar_records=records)
    return build_confirmed_graph_write_plan(
        candidates,
        manifest=_manifest([item.candidate_id for item in candidates]),
        target_namespace="dsl_test_confirmed_write",
    )


def _payload(
    *,
    entity_metadata: dict | None = None,
    relationship_type: str = "DependsOn",
    relationships: list[KgRelationship] | None = None,
) -> DslKgPayload:
    metadata_a = _metadata("ent-a", **(entity_metadata or {}))
    return DslKgPayload(
        chunks=[KgChunk(content="Field A depends on Field B.", source_id="tu-1", metadata=metadata_a)],
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
                keywords=relationship_type,
                source_id="tu-1",
                metadata=_metadata("rel-ab", relationType=relationship_type),
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
            "manifest_id": "MANIFEST-TEST-1",
            "module_name": "module-a",
            "reviewer": "Test Reviewer",
            "decisions": [
                {
                    "candidate_id": candidate_id,
                    "decision": "APPROVED",
                    "reviewer": "Test Reviewer",
                    "reviewer_role": "BA",
                    "decision_reason": "Checked for test manifest.",
                    "evidence_checked": True,
                    "version_checked": True,
                    "term_checked": True,
                }
                for candidate_id in candidate_ids
            ],
        }
    )
