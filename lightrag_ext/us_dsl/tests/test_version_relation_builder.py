from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.kg_metadata_sidecar import build_metadata_sidecar_records
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload, KgChunk, KgEntity
from lightrag_ext.us_dsl.lc_business_qa_eval import MODE_OFFLINE, run_lc_business_qa_ab_eval
from lightrag_ext.us_dsl.lc_mini_graph_smoke import (
    LcMiniGraphSmokeConfig,
    build_lc_mini_kg_payload,
)
from lightrag_ext.us_dsl.lc_us_generation_eval import run_lc_us_generation_ab_eval
from lightrag_ext.us_dsl.version_relation_builder import (
    augment_kg_payload_with_version_relations,
    build_version_relations,
    extract_versioned_semantic_objects,
    serialize_version_coverage_report,
)
from lightrag_ext.us_dsl.version_relation_types import VersionedSemanticObject


def test_has_version_generated_for_semantic_object():
    nodes, relations, report = build_version_relations([_versioned_object("Deal Number")])

    assert nodes
    assert any(item.relation_type == "HasVersion" for item in relations)
    assert report.has_version_count == 1


def test_supersedes_generated_only_with_explicit_metadata():
    obj = _versioned_object(
        "Deal Number",
        rule_version="v2",
        supersedes=["v1"],
        raw={"supersedes": ["v1"]},
    )

    _nodes, relations, report = build_version_relations([obj])

    assert any(item.relation_type == "Supersedes" for item in relations)
    assert report.supersedes_count == 1


def test_no_supersedes_from_source_order_only():
    older = _versioned_object("Deal Number", source_us_id="US-001", rule_version="v1")
    newer = _versioned_object("Deal Number", source_us_id="US-002", rule_version="v2")

    _nodes, relations, report = build_version_relations([older, newer])

    assert all(item.relation_type != "Supersedes" for item in relations)
    assert report.supersedes_count == 0


def test_version_review_required_for_conflicting_latest_flags():
    first = _versioned_object("Deal Number", rule_version="v1", latest_flag=True)
    second = _versioned_object("Deal Number", rule_version="v2", latest_flag=True)

    _nodes, relations, report = build_version_relations([first, second])

    assert any(item.relation_type == "VersionReviewRequired" for item in relations)
    assert report.version_review_required_count > 0


def test_version_conflict_without_supersedes():
    first = _versioned_object("Deal Number", rule_text="Deal Number is editable.")
    second = _versioned_object("Deal Number", rule_text="Deal Number is readonly.")

    _nodes, relations, report = build_version_relations([first, second])

    relation_types = {item.relation_type for item in relations}
    assert "VersionConflictWith" in relation_types
    assert "VersionReviewRequired" in relation_types
    assert "Supersedes" not in relation_types
    assert report.version_conflict_count > 0


def test_missing_evidence_blocks_supersedes():
    obj = VersionedSemanticObject(
        version_group_key="m|d|featurea|fieldspec|deal number|field_table",
        module_code="M",
        domain_code="D",
        feature_key="FeatureA",
        object_type="FieldSpec",
        object_key="Deal Number",
        rule_dimension="field_table",
        source_us_id="US-001",
        source_text_unit_id=None,
        section_type="field_table",
        evidence_text="Deal Number replaces v1.",
        source_span={"start": 0, "end": 10},
        text_hash="hash-1",
        rule_text="Deal Number replaces v1.",
        latest_flag=None,
        version_status=None,
        rule_version="v2",
        supersedes=["v1"],
        version_keywords=[],
        raw={"supersedes": ["v1"]},
    )

    _nodes, _relations, report = build_version_relations([obj])

    assert report.supersedes_count == 0
    assert report.missing_evidence_count == 1


def test_version_group_key_granularity():
    first = _versioned_object("Deal Number", feature_key="FeatureA", rule_text="editable")
    second = _versioned_object("Deal Number", feature_key="FeatureB", rule_text="readonly")

    _nodes, relations, report = build_version_relations([first, second])

    assert report.version_conflict_count == 0
    assert all(item.relation_type != "VersionConflictWith" for item in relations)


def test_augment_kg_payload_with_version_relations_lc():
    payload = build_lc_mini_kg_payload(
        LcMiniGraphSmokeConfig(max_chunks=100, max_entities=100, max_relationships=100)
    )

    assert any(entity.entity_type == "RuleVersion" for entity in payload.entities)
    assert any(item.keywords == "HasVersion" for item in payload.relationships)
    assert payload.metadata["versionRelationCoverage"]["has_version_count"] > 0


def test_sidecar_preserves_version_metadata():
    payload = augment_kg_payload_with_version_relations(_simple_payload())
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_version")

    version_records = [
        record
        for record in records
        if record.entity_type == "RuleVersion" or record.relation_type == "HasVersion"
    ]
    assert version_records
    assert all(record.metadata.get("versionGroupKey") for record in version_records)
    assert all("sourceUsId" in record.metadata for record in version_records)
    assert all("textHash" in record.metadata for record in version_records)


def test_lc_qa_version_case_no_longer_no_coverage():
    report = run_lc_business_qa_ab_eval(
        mode=MODE_OFFLINE,
        max_cases=10,
        use_expanded_subset=True,
    )
    version_case = [
        item for item in report.case_results if item.case.case_id == "LC-QA-009-version-review"
    ][0]

    assert version_case.graph_coverage_status != "none"
    assert "HasVersion" not in version_case.missing_graph_objects
    assert "VersionReviewRequired" not in version_case.missing_graph_objects


def test_lc_usgen_version_case_does_not_hard_judge_latest():
    report = run_lc_us_generation_ab_eval(
        mode="offline",
        max_cases=8,
        use_expanded_subset=True,
    )
    version_case = [
        item for item in report.case_results if item.case.generation_task_type == "VERSION_REVIEW_US"
    ][0]

    assert version_case.graph_coverage_status != "none"
    assert "HasVersion" not in version_case.missing_graph_objects
    assert "VersionReviewRequired" not in version_case.missing_graph_objects
    assert "Open Questions / To Be Confirmed" in version_case.graph_result.generated_us_markdown
    assert "人工确认" in version_case.graph_result.generated_us_markdown
    assert version_case.graph_judgement.adoption_level != "ACCEPT_AS_IS"


def test_no_lc_hardcode_in_version_builder():
    root = Path(__file__).resolve().parents[1]
    forbidden_terms = [
        "LCAB",
        "Acceptable Bank",
        "可接受银行",
        "Bank Status",
        "Swift Code",
        "Transfer To",
    ]
    for relative_path in ["version_relation_builder.py", "version_relation_policy.py"]:
        text = (root / relative_path).read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text


def test_report_serializable():
    objects = [_versioned_object("Deal Number")]
    _nodes, _relations, report = build_version_relations(objects)

    json.dumps(serialize_version_coverage_report(report))


def _simple_payload() -> DslKgPayload:
    return DslKgPayload(
        chunks=[
            KgChunk(
                content="Deal Number is editable.",
                source_id="tu-1",
                metadata=_metadata("Deal Number"),
            )
        ],
        entities=[
            KgEntity(
                entity_name="Deal Number",
                entity_type="FieldSpec",
                description="Deal Number is editable.",
                source_id="tu-1",
                metadata=_metadata("Deal Number"),
            )
        ],
        relationships=[],
    )


def _versioned_object(
    object_key: str,
    *,
    feature_key: str = "FeatureA",
    source_us_id: str = "US-001",
    source_text_unit_id: str | None = "tu-1",
    rule_text: str = "Deal Number is editable.",
    rule_version: str | None = None,
    latest_flag: bool | None = None,
    supersedes: list[str] | None = None,
    raw: dict | None = None,
) -> VersionedSemanticObject:
    metadata = {
        "documentId": "DOC-1",
        "sourceUsId": source_us_id,
        "textUnitId": source_text_unit_id,
        "sourceSpan": {"start": 0, "end": 10},
        "textHash": "hash-1",
        "evidenceText": rule_text,
        "featureKey": feature_key,
        "domainCode": "Ledger",
        "sectionType": "field_table",
        **(raw or {}),
    }
    payload = DslKgPayload(
        chunks=[
            KgChunk(
                content=rule_text,
                source_id=source_text_unit_id or "missing",
                metadata=metadata,
            )
        ],
        entities=[
            KgEntity(
                entity_name=object_key,
                entity_type="FieldSpec",
                description=rule_text,
                source_id=source_text_unit_id or "missing",
                metadata={
                    **metadata,
                    "ruleText": rule_text,
                    "ruleVersion": rule_version,
                    "latestFlag": latest_flag,
                    "supersedes": supersedes or metadata.get("supersedes"),
                },
            )
        ],
        relationships=[],
    )
    return extract_versioned_semantic_objects(kg_payload=payload)[0]


def _metadata(entity_name: str) -> dict:
    return {
        "documentId": "DOC-1",
        "sourceUsId": "US-001",
        "textUnitId": "tu-1",
        "sourceSpan": {"start": 0, "end": 10},
        "textHash": "hash-1",
        "evidenceText": f"{entity_name} is editable.",
        "featureKey": "FeatureA",
        "domainCode": "Ledger",
        "sectionType": "field_table",
        "knowledgeStatus": "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": "AUTO_ACCEPT_FOR_REPORT",
        "confidenceScore": 0.9,
    }
