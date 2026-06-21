from __future__ import annotations

import json
from pathlib import Path

import pytest

from lightrag_ext.us_dsl.candidate_extraction import CandidateExtractionReport
from lightrag_ext.us_dsl.candidate_review_report import build_candidate_review_report
from lightrag_ext.us_dsl.candidate_types import (
    CandidateEntity,
    CandidateRelation,
    KNOWLEDGE_STATUS_CANDIDATE,
    VALIDATION_INVALID_TYPE,
    VALIDATION_REVIEW_REQUIRED,
    VALIDATION_VALID,
)
from lightrag_ext.us_dsl.ingestion_adapter import build_dsl_aware_ingestion_payload
from lightrag_ext.us_dsl.kg_payload_mapper import (
    build_dsl_kg_payload,
    serialize_dsl_kg_payload,
)
from lightrag_ext.us_dsl.kg_schema_policy import FORBIDDEN_RELATION_TYPES
from lightrag_ext.us_dsl.pilot_execution_pack import (
    build_minimal_pilot_dsl_result_from_us_blocks,
)
from lightrag_ext.us_dsl.source_text_unit_builder import detect_us_blocks


FX_THREE_US_FULL = """
## US-FX-001 FX deal entry

- **Primary Domain**: `Ledger`
- **Feature Catalog**: FXDealEntry

【As】FX operator
【I Want】capture FX deal fields
【So That】ledger entry can be reviewed
【Given】the operator opens FX deal entry
【When】the operator inputs deal data
【Then】the system stores Deal Number, Agent Bank, Buy Currency and Sell Currency

### 字段/规则表
| 字段名称 | 类型/编辑形式 | 是否必填 | 数据源/来源 | 定义与说明 |
|---|---|---|---|---|
| Deal Number | Text | 是 | FX deal | Unique FX deal number |
| Agent Bank | Text | 是 | Master data | Agent bank for settlement |

### 详细业务规则
1. Deal Number must be unique.
2. Agent Bank must be selected from acceptable bank master data.

---

## US-FX-002 FX approval

- **Primary Domain**: `Workflow`
- **Feature Catalog**: FXApproval

【As】FX approver
【I Want】approve or reject FX deal
【So That】only valid FX deal can reach final approval
【Given】FX deal is submitted
【When】approver clicks Approve
【Then】workflow records Current Handler and Final Approval

### 待办规则
1. Generate task for Current Handler.
2. Transfer To is available for senior approver.

### DFX / 异常处理
1. No permission users cannot approve.

---

## US-FX-003 FX audit and message

- **Primary Domain**: `AccessAudit`
- **Feature Catalog**: FXAudit

【As】audit user
【I Want】review FX operation history
【So That】I can track OperationLog and AuditLog
【Given】the deal has operation history
【When】the user opens audit history
【Then】the system shows OperationLog and AuditLog

### 提示规则
1. When data is missing, show Not Found.

### DFX / 异常处理
1. All approve and reject actions write AuditLog.
""".strip()

LC_SOURCE = Path("/Users/hufaofao/Projects/LC_Acceptable_Bank_US_v1.md")


def test_build_kg_payload_fx():
    payload, candidate_report, review_report = _build_fx_reports()

    kg_payload = build_dsl_kg_payload(
        ingestion_payload=payload,
        candidate_extraction_report=candidate_report,
        candidate_review_report=review_report,
    )

    assert kg_payload.summary["chunk_count"] > 0
    assert kg_payload.summary["entity_count"] > 0
    assert kg_payload.summary["relationship_count"] > 0
    assert kg_payload.summary["graph_write_called"] is False
    assert kg_payload.summary["formal_graph_eligible_count"] == 0


def test_build_kg_payload_lc():
    content = _load_lc_content()
    blocks = detect_us_blocks(content)
    assert len(blocks) == 66
    dsl_result = build_minimal_pilot_dsl_result_from_us_blocks(
        blocks,
        module_code="LCAB",
    )
    ingestion_payload = build_dsl_aware_ingestion_payload(
        content,
        document_id="DOC_LCAB_001",
        dsl_result=dsl_result,
        file_path=str(LC_SOURCE),
    )

    kg_payload = build_dsl_kg_payload(ingestion_payload=ingestion_payload)

    assert kg_payload.summary["user_story_count"] == 66
    assert kg_payload.summary["chunk_count"] == 291
    assert kg_payload.summary["feature_count"] > 0
    assert kg_payload.summary["evidence_span_count"] > 0


def test_entities_have_metadata():
    kg_payload = _build_fx_kg_payload()

    for entity in kg_payload.entities:
        metadata = entity.metadata
        assert "sourceUsId" in metadata
        assert "featureKey" in metadata
        assert "domainCode" in metadata
        assert "knowledgeStatus" in metadata
        assert "textHash" in metadata


def test_relationships_have_evidence():
    kg_payload = _build_fx_kg_payload()

    for relationship in kg_payload.relationships:
        metadata = relationship.metadata
        assert relationship.source_id
        assert metadata.get("relationType")
        assert metadata.get("knowledgeStatus")
        assert "sourceSpan" in metadata
        assert "textHash" in metadata


def test_no_confirmed_in_payload():
    kg_payload = _build_fx_kg_payload()

    statuses = [
        item.metadata.get("knowledgeStatus")
        for item in [*kg_payload.entities, *kg_payload.relationships, *kg_payload.chunks]
    ]
    assert "Confirmed" not in statuses


def test_review_required_excluded_by_default():
    kg_payload = _build_fx_kg_payload()

    assert "Ambiguous FX Thing" not in {entity.entity_name for entity in kg_payload.entities}
    assert kg_payload.summary["review_required_excluded_count"] >= 1


def test_info_only_excluded_by_default():
    kg_payload = _build_fx_kg_payload()

    assert "Low Risk Note" not in {entity.entity_name for entity in kg_payload.entities}
    assert kg_payload.summary["info_only_excluded_count"] >= 1


def test_invalid_relation_excluded():
    kg_payload = _build_fx_kg_payload()

    assert all(item.keywords != "NoSuchRelation" for item in kg_payload.relationships)
    assert kg_payload.summary["invalid_relation_excluded_count"] >= 1


def test_forbidden_relation_not_output():
    kg_payload = _build_fx_kg_payload()

    assert FORBIDDEN_RELATION_TYPES.isdisjoint(
        {item.keywords for item in kg_payload.relationships}
    )


def test_version_edges():
    kg_payload = _build_fx_kg_payload()

    assert any(item.keywords == "Supersedes" for item in kg_payload.relationships)
    assert "Bank Rating" in kg_payload.version_mapping


def test_evidence_edges():
    kg_payload = _build_fx_kg_payload()

    assert any(item.keywords == "SupportedByEvidence" for item in kg_payload.relationships)


def test_term_edges():
    kg_payload = _build_fx_kg_payload()

    assert any(item.keywords == "NormalizedTo" for item in kg_payload.relationships)


def test_payload_serializable():
    kg_payload = _build_fx_kg_payload()

    json.dumps(serialize_dsl_kg_payload(kg_payload))


def test_formal_graph_disabled():
    payload, candidate_report, review_report = _build_fx_reports()

    kg_payload = build_dsl_kg_payload(
        ingestion_payload=payload,
        candidate_extraction_report=candidate_report,
        candidate_review_report=review_report,
        target="formal_graph",
    )

    assert kg_payload.summary["formal_graph_enabled"] is False
    assert kg_payload.summary["disabled"] is True
    assert kg_payload.entities == []
    assert kg_payload.relationships == []


def test_metadata_not_lost_if_lightrag_custom_kg_limited():
    kg_payload = _build_fx_kg_payload()
    serialized = serialize_dsl_kg_payload(kg_payload)

    assert serialized["metadata"]["lightRagCustomKgMetadataPassThrough"] is False
    assert serialized["entities"][0]["metadata"]
    assert serialized["relationships"][0]["metadata"]


def _build_fx_kg_payload():
    payload, candidate_report, review_report = _build_fx_reports()
    return build_dsl_kg_payload(
        ingestion_payload=payload,
        candidate_extraction_report=candidate_report,
        candidate_review_report=review_report,
    )


def _build_fx_reports():
    blocks = detect_us_blocks(FX_THREE_US_FULL)
    dsl_result = build_minimal_pilot_dsl_result_from_us_blocks(
        blocks,
        module_code="FX",
    )
    payload = build_dsl_aware_ingestion_payload(
        FX_THREE_US_FULL,
        document_id="DOC_FX_001",
        dsl_result=dsl_result,
        file_path="fx_fixture.md",
    )
    contexts = {item.text_unit_id: item for item in payload.metadata_payload}
    field_context = _first_context(payload, "field_table")
    task_context = _first_context(payload, "task_rule")
    message_context = _first_context(payload, "message_rule")
    fallback_context = field_context

    entities = [
        _entity("ent-field", "Deal Number", "FieldSpec", field_context),
        _entity(
            "ent-version",
            "Bank Rating",
            "FieldSpec",
            field_context,
            raw={
                "ruleVersion": "v2",
                "versionStatus": "latest",
                "latestFlag": True,
                "supersedes": "v1",
            },
        ),
        _entity(
            "ent-term",
            "Swift Code",
            "FieldSpec",
            field_context,
            raw={"originalTerm": "Swift Code", "canonicalTerm": "BIC"},
        ),
        _entity(
            "ent-auto",
            "Transfer To",
            "TaskRule",
            task_context,
            raw={"autoResolved": True},
        ),
        _entity(
            "ent-info",
            "Low Risk Note",
            "DomainObject",
            fallback_context,
            domain_code="Other",
            section_type="unknown",
            confidence_score=0.4,
        ),
        _entity(
            "ent-review",
            "Ambiguous FX Thing",
            "UnclearType",
            message_context,
            validation_status=VALIDATION_INVALID_TYPE,
            raw={"allowedEntityTypes": ["FieldSpec"]},
        ),
    ]
    feature_key = field_context.feature_key or "Ledger:FX:FXDealEntry"
    relations = [
        _relation(
            "rel-field",
            feature_key,
            "Deal Number",
            "HasFieldSpec",
            field_context,
        ),
        _relation(
            "rel-forbidden",
            feature_key,
            "Deal Number",
            "has_child",
            field_context,
        ),
        _relation(
            "rel-invalid",
            feature_key,
            "Deal Number",
            "NoSuchRelation",
            field_context,
            validation_status=VALIDATION_INVALID_TYPE,
            raw={"allowedRelationTypes": ["HasFieldSpec"]},
        ),
    ]
    candidate_report = _candidate_report(payload, entities, relations)
    review_report = build_candidate_review_report(
        [*entities, *relations],
        document_id=payload.document_id,
    )
    assert contexts
    return payload, candidate_report, review_report


def _candidate_report(
    payload,
    entities: list[CandidateEntity],
    relations: list[CandidateRelation],
) -> CandidateExtractionReport:
    return CandidateExtractionReport(
        enabled=True,
        skipped=False,
        skip_reason=None,
        extraction_run_id="candidate-run-test",
        document_id=payload.document_id,
        sample_count=3,
        native_extract_called=False,
        live_llm_used=False,
        candidate_entity_count=len(entities),
        candidate_relation_count=len(relations),
        valid_entity_count=sum(item.validation_status == VALIDATION_VALID for item in entities),
        valid_relation_count=sum(item.validation_status == VALIDATION_VALID for item in relations),
        invalid_entity_count=sum(
            item.validation_status == VALIDATION_INVALID_TYPE for item in entities
        ),
        invalid_relation_count=sum(
            item.validation_status == VALIDATION_INVALID_TYPE for item in relations
        ),
        review_required_count=sum(
            item.validation_status == VALIDATION_REVIEW_REQUIRED
            for item in [*entities, *relations]
        ),
        missing_evidence_count=0,
        duplicate_candidate_count=0,
        candidate_store_written_count=0,
        candidate_store_deleted_count=0,
        candidate_store_reset_supported=True,
        rollback_passed=True,
        graph_written=False,
        merge_called=False,
        entities_vdb_written=False,
        relationships_vdb_written=False,
        full_docs_written=False,
        doc_status_written=False,
        quality_summary={"candidateOnly": True},
        recommended_next_step="BUILD_CANDIDATE_REVIEW_REPORT",
        candidate_entities=entities,
        candidate_relations=relations,
    )


def _entity(
    candidate_id: str,
    entity_name: str,
    entity_type: str,
    context,
    *,
    validation_status: str = VALIDATION_VALID,
    raw: dict | None = None,
    domain_code: str | None = None,
    section_type: str | None = None,
    confidence_score: float = 0.9,
) -> CandidateEntity:
    evidence_text = _evidence_text(context)
    return CandidateEntity(
        candidate_id=candidate_id,
        entity_name=entity_name,
        entity_type=entity_type,
        description=f"{entity_name} is grounded in source evidence.",
        domain_code=domain_code or context.domain_code,
        feature_key=context.feature_key,
        source_us_id=context.source_us_id,
        source_text_unit_id=context.text_unit_id,
        section_type=section_type or context.section_type,
        source_span=context.source_span,
        text_hash=context.text_hash,
        evidence_text=evidence_text,
        extraction_run_id="candidate-run-test",
        knowledge_status=KNOWLEDGE_STATUS_CANDIDATE,
        validation_status=validation_status,
        confidence_score=confidence_score,
        raw={
            "allowedEntityTypes": ["FieldSpec", "TaskRule", "DomainObject"],
            "allowedRelationTypes": ["HasFieldSpec", "HasTaskRule"],
            **(raw or {}),
        },
    )


def _relation(
    candidate_id: str,
    source_entity_name: str,
    target_entity_name: str,
    relation_type: str,
    context,
    *,
    validation_status: str = VALIDATION_VALID,
    raw: dict | None = None,
) -> CandidateRelation:
    return CandidateRelation(
        candidate_id=candidate_id,
        source_entity_name=source_entity_name,
        target_entity_name=target_entity_name,
        relation_type=relation_type,
        relationship_keywords=relation_type,
        description=f"{source_entity_name} {relation_type} {target_entity_name}.",
        domain_code=context.domain_code,
        feature_key=context.feature_key,
        source_us_id=context.source_us_id,
        source_text_unit_id=context.text_unit_id,
        section_type=context.section_type,
        source_span=context.source_span,
        text_hash=context.text_hash,
        evidence_text=_evidence_text(context),
        extraction_run_id="candidate-run-test",
        knowledge_status=KNOWLEDGE_STATUS_CANDIDATE,
        validation_status=validation_status,
        confidence_score=0.9,
        raw={
            "allowedRelationTypes": ["HasFieldSpec", "HasTaskRule"],
            **(raw or {}),
        },
    )


def _first_context(payload, section_type: str):
    for item in payload.metadata_payload:
        if item.section_type == section_type:
            return item
    return payload.metadata_payload[0]


def _evidence_text(context) -> str:
    return (
        f"{context.source_us_id} {context.feature_key} {context.section_type} "
        f"Deal Number Agent Bank Swift Code Bank Rating Transfer To"
    )


def _load_lc_content() -> str:
    if not LC_SOURCE.exists():
        pytest.skip(f"LC fixture not found: {LC_SOURCE}")
    return LC_SOURCE.read_text(encoding="utf-8")
