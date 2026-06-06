from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import os
import time
from typing import Any, ClassVar

from .candidate_extraction import CandidateExtractionReport
from .candidate_review_report import build_candidate_review_report
from .candidate_types import (
    CandidateEntity,
    CandidateRelation,
    KNOWLEDGE_STATUS_CANDIDATE,
    VALIDATION_INVALID_TYPE,
    VALIDATION_VALID,
)
from .ingestion_adapter import build_dsl_aware_ingestion_payload
from .kg_metadata_sidecar import (
    build_graph_insert_sidecar_records,
    validate_graph_insert_sidecar_alignment,
)
from .kg_payload_mapper import build_dsl_kg_payload
from .kg_payload_types import DslKgPayload
from .kg_real_graph_smoke import (
    SMOKE_GRAPH_STORAGE,
    RealCustomKgSmokeConfig,
    _run_real_custom_kg_smoke_async,
    without_graph_remote_env,
)
from .kg_schema_policy import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_RELATION_TYPES,
    FORBIDDEN_RELATION_TYPES,
)
from .kg_test_graph_write import to_lightrag_custom_kg_input
from .pilot_execution_pack import build_minimal_pilot_dsl_result_from_us_blocks
from .source_text_unit_builder import detect_us_blocks


ENABLE_FX_MINI_SMOKE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_FX_MINI_GRAPH_SMOKE"
FX_MINI_NAMESPACE = "dsl_test_fx_mini_graph_smoke"
FX_MINI_WORKSPACE = "dsl_test_fx_mini_graph_smoke"
FX_SOURCE_NAME = "FX_THREE_US_FULL"

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


@dataclass
class FxMiniGraphSmokeConfig:
    __test__: ClassVar[bool] = False

    enabled: bool = False
    source: str = "fx"
    namespace: str = FX_MINI_NAMESPACE
    workspace: str = FX_MINI_WORKSPACE
    max_chunks: int = 3
    max_entities: int = 5
    max_relationships: int = 3
    timeout_seconds: int = 120
    use_temp_working_dir: bool = True
    force_local_graph_storage: bool = True
    local_graph_storage: str = SMOKE_GRAPH_STORAGE
    isolate_remote_graph_env: bool = True
    allow_neo4j: bool = False
    use_fake_embedding: bool = True
    use_fake_llm: bool = True
    cleanup_after_run: bool = True
    feature_flag_name: str = "enable_dsl_aware_fx_mini_graph_smoke"

    @classmethod
    def from_env(cls) -> "FxMiniGraphSmokeConfig":
        return cls(enabled=os.getenv(ENABLE_FX_MINI_SMOKE_ENV) == "1")


@dataclass
class FxMiniGraphSmokeReport:
    __test__: ClassVar[bool] = False

    enabled: bool
    skipped: bool
    skip_reason: str | None
    working_dir: str | None
    workspace: str
    graph_storage_type: str
    source: str
    selected_chunk_count: int
    selected_entity_count: int
    selected_relationship_count: int
    sidecar_record_count: int
    sidecar_alignment_passed: bool
    ainsert_custom_kg_called: bool
    graph_write_attempted: bool
    graph_write_succeeded: bool
    neo4j_connected: bool
    production_namespace_blocked: bool
    fake_embedding_used: bool
    fake_llm_used: bool
    cleanup_passed: bool
    elapsed_ms: int
    forbidden_relation_count: int
    confirmed_count: int
    review_required_written: bool
    info_only_written: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommended_next_step: str = ""


def build_fx_kg_payload() -> DslKgPayload:
    ingestion_payload, candidate_report, review_report = _build_fx_reports()
    return build_dsl_kg_payload(
        ingestion_payload=ingestion_payload,
        candidate_extraction_report=candidate_report,
        candidate_review_report=review_report,
    )


def build_fx_mini_kg_payload(
    *,
    max_chunks: int = 3,
    max_entities: int = 5,
    max_relationships: int = 3,
) -> DslKgPayload:
    full_payload = build_fx_kg_payload()
    selected_relationships = _select_fx_mini_relationships(full_payload, max_relationships)
    selected_entity_names: list[str] = []
    for relationship in selected_relationships:
        _append_unique(selected_entity_names, relationship.src_id)
        _append_unique(selected_entity_names, relationship.tgt_id)

    entity_by_name = {entity.entity_name: entity for entity in full_payload.entities}
    selected_entities = [
        entity_by_name[name]
        for name in selected_entity_names
        if name in entity_by_name
    ][:max_entities]
    selected_entity_name_set = {entity.entity_name for entity in selected_entities}
    selected_relationships = [
        relationship
        for relationship in selected_relationships
        if relationship.src_id in selected_entity_name_set
        and relationship.tgt_id in selected_entity_name_set
    ][:max_relationships]

    selected_source_ids: list[str] = []
    for entity in selected_entities:
        _append_unique(selected_source_ids, entity.source_id)
    for relationship in selected_relationships:
        _append_unique(selected_source_ids, relationship.source_id)

    chunk_by_id = {chunk.source_id: chunk for chunk in full_payload.chunks}
    selected_chunks = [
        chunk_by_id[source_id]
        for source_id in selected_source_ids
        if source_id in chunk_by_id
    ][:max_chunks]
    selected_chunk_ids = {chunk.source_id for chunk in selected_chunks}
    selected_entities = [
        entity for entity in selected_entities if entity.source_id in selected_chunk_ids
    ][:max_entities]
    selected_entity_name_set = {entity.entity_name for entity in selected_entities}
    selected_relationships = [
        relationship
        for relationship in selected_relationships
        if relationship.source_id in selected_chunk_ids
        and relationship.src_id in selected_entity_name_set
        and relationship.tgt_id in selected_entity_name_set
    ][:max_relationships]

    return DslKgPayload(
        chunks=selected_chunks,
        entities=selected_entities,
        relationships=selected_relationships,
        metadata={
            **full_payload.metadata,
            "source": FX_SOURCE_NAME,
            "miniSubset": True,
            "maxChunks": max_chunks,
            "maxEntities": max_entities,
            "maxRelationships": max_relationships,
        },
        issues=list(full_payload.issues),
        summary={
            "source": FX_SOURCE_NAME,
            "selected_chunk_count": len(selected_chunks),
            "selected_entity_count": len(selected_entities),
            "selected_relationship_count": len(selected_relationships),
            "full_chunk_count": len(full_payload.chunks),
            "full_entity_count": len(full_payload.entities),
            "full_relationship_count": len(full_payload.relationships),
            "graph_write_called": False,
        },
        entity_vdb_payload=[],
        relationship_vdb_payload=[],
        evidence_mapping=dict(full_payload.evidence_mapping),
        version_mapping=dict(full_payload.version_mapping),
    )


def build_fx_mini_custom_kg_input(
    config: FxMiniGraphSmokeConfig | None = None,
) -> dict[str, list[dict[str, Any]]]:
    config = config or FxMiniGraphSmokeConfig()
    payload = build_fx_mini_kg_payload(
        max_chunks=config.max_chunks,
        max_entities=config.max_entities,
        max_relationships=config.max_relationships,
    )
    return to_lightrag_custom_kg_input(payload)


def run_fx_mini_graph_smoke(
    *,
    config: FxMiniGraphSmokeConfig | None = None,
) -> FxMiniGraphSmokeReport:
    config = config or FxMiniGraphSmokeConfig.from_env()
    started = time.monotonic()
    payload = build_fx_mini_kg_payload(
        max_chunks=config.max_chunks,
        max_entities=config.max_entities,
        max_relationships=config.max_relationships,
    )
    custom_kg = to_lightrag_custom_kg_input(payload)
    sidecar_records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace=config.namespace,
    )
    alignment = validate_graph_insert_sidecar_alignment(custom_kg, sidecar_records)
    guard_issues = _custom_kg_guard_issues(payload, custom_kg)
    counts = _status_counts(payload)

    base_report = _base_report(
        config,
        payload=payload,
        sidecar_record_count=len(sidecar_records),
        sidecar_alignment_passed=alignment.pass_status == "PASS",
        forbidden_relation_count=sum(
            1 for item in payload.relationships if item.keywords in FORBIDDEN_RELATION_TYPES
        ),
        confirmed_count=counts["confirmed"],
        review_required_written=counts["review_required"] > 0,
        info_only_written=counts["info_only"] > 0,
        started=started,
    )

    if not config.enabled:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="Feature flag enable_dsl_aware_fx_mini_graph_smoke is disabled.",
            elapsed_ms=_elapsed_ms(started),
            recommended_next_step="ENABLE_FEATURE_FLAG_TO_TEST_GRAPH_WRITE",
        )
    if not config.force_local_graph_storage or config.local_graph_storage != SMOKE_GRAPH_STORAGE:
        return _blocked_report(
            base_report,
            "FX_MINI_GRAPH_UNSUPPORTED",
            "FX mini smoke requires local NetworkXStorage.",
            "FIX_GRAPH_STORAGE_CONFIG",
            started,
        )
    if config.allow_neo4j:
        return _blocked_report(
            base_report,
            "NEO4J_FORBIDDEN",
            "FX mini smoke must not allow Neo4j.",
            "DO_NOT_WRITE_GRAPH",
            started,
        )
    if not config.use_fake_embedding or not config.use_fake_llm:
        return _blocked_report(
            base_report,
            "FAKE_MODEL_REQUIRED",
            "FX mini smoke must use fake embedding and fake LLM.",
            "FIX_GRAPH_STORAGE_CONFIG",
            started,
        )
    if alignment.pass_status != "PASS":
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="SIDECAR_ALIGNMENT_FAIL",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                {
                    "severity": "ERROR",
                    "code": "SIDECAR_ALIGNMENT_FAIL",
                    "message": "FX mini sidecar alignment failed.",
                }
            ],
            recommended_next_step="FIX_SIDECAR_ALIGNMENT",
        )
    if guard_issues:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason=guard_issues[0]["code"],
            elapsed_ms=_elapsed_ms(started),
            issues=guard_issues,
            recommended_next_step=(
                "FIX_KG_PAYLOAD_FILTERING"
                if guard_issues[0]["code"] == "FORBIDDEN_RELATION_BLOCKED"
                else "DO_NOT_WRITE_GRAPH"
            ),
        )
    if not config.use_temp_working_dir:
        return _blocked_report(
            base_report,
            "TEMP_WORKING_DIR_REQUIRED",
            "FX mini smoke requires disposable temp working_dir.",
            "FIX_GRAPH_STORAGE_CONFIG",
            started,
        )

    real_config = RealCustomKgSmokeConfig(
        enabled=True,
        use_temp_working_dir=True,
        namespace=config.namespace,
        workspace=config.workspace,
        max_chunks=config.max_chunks,
        max_entities=config.max_entities,
        max_relationships=config.max_relationships,
        timeout_seconds=config.timeout_seconds,
        use_fake_embedding=config.use_fake_embedding,
        use_fake_llm=config.use_fake_llm,
        allow_neo4j=False,
        cleanup_after_run=config.cleanup_after_run,
        force_local_graph_storage=True,
        local_graph_storage=config.local_graph_storage,
        isolate_remote_graph_env=config.isolate_remote_graph_env,
    )

    try:
        if config.isolate_remote_graph_env:
            with without_graph_remote_env():
                result = asyncio.run(
                    asyncio.wait_for(
                        _run_real_custom_kg_smoke_async(real_config, custom_kg),
                        timeout=config.timeout_seconds,
                    )
                )
        else:
            result = asyncio.run(
                asyncio.wait_for(
                    _run_real_custom_kg_smoke_async(real_config, custom_kg),
                    timeout=config.timeout_seconds,
                )
            )
    except TimeoutError:
        return _replace_report(
            base_report,
            skipped=False,
            skip_reason="TIMEOUT",
            graph_write_attempted=True,
            elapsed_ms=_elapsed_ms(started),
            issues=[
                {
                    "severity": "ERROR",
                    "code": "TIMEOUT",
                    "message": "FX mini graph smoke timed out.",
                }
            ],
            recommended_next_step="FIX_CUSTOM_KG_TIMEOUT",
        )
    except Exception as exc:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="FX_MINI_GRAPH_UNSUPPORTED",
            graph_write_attempted=True,
            elapsed_ms=_elapsed_ms(started),
            issues=[
                {
                    "severity": "ERROR",
                    "code": "FX_MINI_GRAPH_UNSUPPORTED",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            ],
            recommended_next_step="FIX_GRAPH_STORAGE_CONFIG",
        )

    return _replace_report(
        base_report,
        skipped=False,
        skip_reason=None,
        working_dir=result["working_dir"],
        ainsert_custom_kg_called=True,
        graph_write_attempted=True,
        graph_write_succeeded=True,
        neo4j_connected=False,
        cleanup_passed=result["cleanup_passed"],
        elapsed_ms=_elapsed_ms(started),
        recommended_next_step=(
            "TRY_LC_MINI_GRAPH_SMOKE"
            if result["cleanup_passed"]
            else "FIX_GRAPH_CLEANUP"
        ),
    )


def serialize_fx_mini_graph_smoke_report(
    report: FxMiniGraphSmokeReport,
) -> dict[str, Any]:
    return asdict(report)


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
        _relation("rel-field", feature_key, "Deal Number", "HasFieldSpec", field_context),
        _relation("rel-forbidden", feature_key, "Deal Number", "has_child", field_context),
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
    return payload, candidate_report, review_report


def _select_fx_mini_relationships(
    payload: DslKgPayload,
    max_relationships: int,
):
    selected = []
    priorities = [
        lambda item: item.keywords == "HasFieldSpec" and item.tgt_id == "Deal Number",
        lambda item: item.keywords == "SupportedByEvidence" and item.src_id == "Deal Number",
        lambda item: item.keywords == "SupportedByEvidence" and item.src_id == "Transfer To",
    ]
    for predicate in priorities:
        for relationship in payload.relationships:
            if predicate(relationship) and relationship not in selected:
                selected.append(relationship)
                break
    for relationship in payload.relationships:
        if len(selected) >= max_relationships:
            break
        if (
            relationship.keywords in ALLOWED_RELATION_TYPES
            and relationship.keywords not in FORBIDDEN_RELATION_TYPES
            and relationship not in selected
        ):
            selected.append(relationship)
    return selected[:max_relationships]


def _custom_kg_guard_issues(
    payload: DslKgPayload,
    custom_kg: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    chunk_source_ids = {item["source_id"] for item in custom_kg["chunks"]}
    entity_names = {item["entity_name"] for item in custom_kg["entities"]}
    for entity in custom_kg["entities"]:
        if entity["source_id"] not in chunk_source_ids:
            issues.append(
                _issue(
                    "ENTITY_SOURCE_ID_MISSING_CHUNK",
                    f"Entity source_id has no matching chunk: {entity['entity_name']}",
                )
            )
        if entity["entity_type"] not in ALLOWED_ENTITY_TYPES:
            issues.append(
                _issue(
                    "INVALID_ENTITY_TYPE_BLOCKED",
                    f"Entity type is not allowed: {entity['entity_type']}",
                )
            )
    for relationship in custom_kg["relationships"]:
        if relationship["source_id"] not in chunk_source_ids:
            issues.append(
                _issue(
                    "RELATION_SOURCE_ID_MISSING_CHUNK",
                    "Relationship source_id has no matching chunk.",
                )
            )
        if relationship["src_id"] not in entity_names or relationship["tgt_id"] not in entity_names:
            issues.append(
                _issue(
                    "RELATION_ENDPOINT_MISSING_ENTITY",
                    "Relationship endpoint is missing from selected entities.",
                )
            )
        if relationship["keywords"] in FORBIDDEN_RELATION_TYPES:
            issues.append(
                _issue("FORBIDDEN_RELATION_BLOCKED", "Forbidden relation found.")
            )
        if relationship["keywords"] not in ALLOWED_RELATION_TYPES:
            issues.append(
                _issue(
                    "INVALID_RELATION_TYPE_BLOCKED",
                    f"Relation type is not allowed: {relationship['keywords']}",
                )
            )
    counts = _status_counts(payload)
    if counts["confirmed"]:
        issues.append(_issue("CONFIRMED_PAYLOAD_BLOCKED", "Confirmed payload is forbidden."))
    if counts["review_required"]:
        issues.append(
            _issue("REVIEW_REQUIRED_PAYLOAD_BLOCKED", "ReviewRequired payload is forbidden.")
        )
    if counts["info_only"]:
        issues.append(_issue("INFO_ONLY_PAYLOAD_BLOCKED", "InfoOnly payload is forbidden."))
    return issues


def _status_counts(payload: DslKgPayload) -> dict[str, int]:
    statuses = [
        str(item.metadata.get("knowledgeStatus") or "")
        for item in [*payload.entities, *payload.relationships]
    ]
    return {
        "confirmed": sum(status == "Confirmed" for status in statuses),
        "review_required": sum(status == "ReviewRequired" for status in statuses),
        "info_only": sum(status == "InfoOnly" for status in statuses),
    }


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
        extraction_run_id="candidate-run-fx-mini",
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
        extraction_run_id="candidate-run-fx-mini",
        knowledge_status=KNOWLEDGE_STATUS_CANDIDATE,
        validation_status=validation_status,
        confidence_score=0.9,
        raw={"allowedRelationTypes": ["HasFieldSpec", "HasTaskRule"], **(raw or {})},
    )


def _candidate_report(
    payload,
    entities: list[CandidateEntity],
    relations: list[CandidateRelation],
) -> CandidateExtractionReport:
    return CandidateExtractionReport(
        enabled=True,
        skipped=False,
        skip_reason=None,
        extraction_run_id="candidate-run-fx-mini",
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
        review_required_count=0,
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


def _base_report(
    config: FxMiniGraphSmokeConfig,
    *,
    payload: DslKgPayload,
    sidecar_record_count: int,
    sidecar_alignment_passed: bool,
    forbidden_relation_count: int,
    confirmed_count: int,
    review_required_written: bool,
    info_only_written: bool,
    started: float,
) -> FxMiniGraphSmokeReport:
    return FxMiniGraphSmokeReport(
        enabled=config.enabled,
        skipped=True,
        skip_reason=None,
        working_dir=None,
        workspace=config.workspace,
        graph_storage_type=config.local_graph_storage,
        source=FX_SOURCE_NAME,
        selected_chunk_count=len(payload.chunks),
        selected_entity_count=len(payload.entities),
        selected_relationship_count=len(payload.relationships),
        sidecar_record_count=sidecar_record_count,
        sidecar_alignment_passed=sidecar_alignment_passed,
        ainsert_custom_kg_called=False,
        graph_write_attempted=False,
        graph_write_succeeded=False,
        neo4j_connected=False,
        production_namespace_blocked=False,
        fake_embedding_used=config.use_fake_embedding,
        fake_llm_used=config.use_fake_llm,
        cleanup_passed=True,
        elapsed_ms=_elapsed_ms(started),
        forbidden_relation_count=forbidden_relation_count,
        confirmed_count=confirmed_count,
        review_required_written=review_required_written,
        info_only_written=info_only_written,
        issues=[],
        recommended_next_step="",
    )


def _blocked_report(
    base_report: FxMiniGraphSmokeReport,
    code: str,
    message: str,
    recommended_next_step: str,
    started: float,
) -> FxMiniGraphSmokeReport:
    return _replace_report(
        base_report,
        skipped=True,
        skip_reason=code,
        elapsed_ms=_elapsed_ms(started),
        issues=[_issue(code, message)],
        recommended_next_step=recommended_next_step,
    )


def _replace_report(
    report: FxMiniGraphSmokeReport,
    **changes: Any,
) -> FxMiniGraphSmokeReport:
    data = asdict(report)
    data.update(changes)
    return FxMiniGraphSmokeReport(**data)


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": message}


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


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


__all__ = [
    "ENABLE_FX_MINI_SMOKE_ENV",
    "FX_THREE_US_FULL",
    "FxMiniGraphSmokeConfig",
    "FxMiniGraphSmokeReport",
    "build_fx_kg_payload",
    "build_fx_mini_custom_kg_input",
    "build_fx_mini_kg_payload",
    "run_fx_mini_graph_smoke",
    "serialize_fx_mini_graph_smoke_report",
]
