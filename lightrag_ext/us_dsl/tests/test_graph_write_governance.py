from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.graph_write_governance import (
    serialize_graph_write_governance_report,
    validate_graph_write_plan,
)
from lightrag_ext.us_dsl.kg_metadata_sidecar import build_metadata_sidecar_records
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship
from lightrag_ext.us_dsl.promotion_gate import (
    build_confirmed_graph_write_plan,
    build_promotion_candidates,
)
from lightrag_ext.us_dsl.promotion_manifest import promotion_manifest_from_dict


def test_governance_blocks_production_namespace():
    plan = _plan(namespace="production")

    report = validate_graph_write_plan(plan)

    assert report.pass_status == "FAIL"
    assert report.production_write_blocked is True
    assert "PRODUCTION_WRITE_BLOCKED" in report.issues


def test_governance_requires_test_namespace():
    plan = _plan(namespace="staging")

    report = validate_graph_write_plan(plan)

    assert report.pass_status == "FAIL"
    assert "TARGET_NAMESPACE_NOT_TEST" in report.issues


def test_governance_passes_test_plan():
    plan = _plan(namespace="dsl_test_governance")

    report = validate_graph_write_plan(plan)

    assert report.pass_status == "PASS"
    assert report.rollback_plan_present is True
    assert report.audit_event_count > 0
    assert report.idempotency_key_duplicate_count == 0


def test_no_graph_write_by_default():
    root = Path(__file__).resolve().parents[1]
    text = (root / "promotion_gate.py").read_text(encoding="utf-8")

    assert "ainsert_custom_kg" not in text
    assert "upsert_node" not in text
    assert "upsert_edge" not in text


def test_no_lc_hardcode_in_promotion_policy():
    root = Path(__file__).resolve().parents[1]
    forbidden_terms = [
        "LCAB",
        "Acceptable Bank",
        "可接受银行",
        "Bank Status",
        "Swift Code",
        "Transfer To",
    ]
    for relative_path in [
        "promotion_policy.py",
        "promotion_gate.py",
        "graph_write_governance.py",
    ]:
        text = (root / relative_path).read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text


def test_graph_write_governance_report_serializable():
    report = validate_graph_write_plan(_plan(namespace="dsl_test_governance"))

    json.dumps(serialize_graph_write_governance_report(report))


def _plan(namespace: str):
    payload = _payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_governance")
    candidates = build_promotion_candidates(kg_payload=payload, sidecar_records=records)
    approved = [item.candidate_id for item in candidates if item.eligibility_status == "ELIGIBLE"][:3]
    return build_confirmed_graph_write_plan(
        candidates,
        manifest=_manifest(approved),
        target_namespace=namespace,
    )


def _payload() -> DslKgPayload:
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
        relationships=[
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
