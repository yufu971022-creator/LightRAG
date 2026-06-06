from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import time
from typing import Any, ClassVar

from .candidate_extraction import CandidateExtractionReport
from .candidate_review_report import build_candidate_review_report
from .candidate_types import (
    CandidateEntity,
    CandidateRelation,
    KNOWLEDGE_STATUS_CANDIDATE,
    VALIDATION_VALID,
)
from .ingestion_adapter import build_dsl_aware_ingestion_payload
from .kg_metadata_sidecar import (
    build_graph_insert_sidecar_records,
    validate_graph_insert_sidecar_alignment,
)
from .kg_payload_mapper import build_dsl_kg_payload
from .kg_payload_types import DslKgPayload, KgEntity, KgRelationship
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


ENABLE_LC_MINI_SMOKE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_LC_MINI_GRAPH_SMOKE"
ENABLE_LC_SUBSET_SMOKE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_LC_SUBSET_GRAPH_SMOKE"
LC_FILE_PATH_ENV = "LIGHTRAG_DSL_LC_FILE_PATH"
LC_MINI_NAMESPACE = "dsl_test_lc_mini_graph_smoke"
LC_MINI_WORKSPACE = "dsl_test_lc_mini_graph_smoke"
LC_SOURCE_NAME = "LC_Acceptable_Bank_US_v1.md"
DEFAULT_LC_FILE = Path("/Users/hufaofao/Projects/LC_Acceptable_Bank_US_v1.md")
FALLBACK_LC_FIXTURE = (
    Path(__file__).resolve().parent
    / "tests"
    / "fixtures"
    / "LC_Acceptable_Bank_US_v1.md"
)
EXPECTED_SOURCE_US_COUNT = 66
EXPECTED_FIRST_US_ID = "US-LCAB-001"
EXPECTED_LAST_US_ID = "US-LCAB-066"
EXPECTED_SOURCE_TEXT_UNIT_COUNT = 291


@dataclass
class LcMiniGraphSmokeConfig:
    __test__: ClassVar[bool] = False

    enabled: bool = False
    source: str = "lc"
    lc_file_path: str | None = None
    namespace: str = LC_MINI_NAMESPACE
    workspace: str = LC_MINI_WORKSPACE
    max_chunks: int = 5
    max_entities: int = 10
    max_relationships: int = 5
    timeout_seconds: int = 120
    use_temp_working_dir: bool = True
    force_local_graph_storage: bool = True
    local_graph_storage: str = SMOKE_GRAPH_STORAGE
    isolate_remote_graph_env: bool = True
    allow_neo4j: bool = False
    use_fake_embedding: bool = True
    use_fake_llm: bool = True
    cleanup_after_run: bool = True
    feature_flag_name: str = "enable_dsl_aware_lc_mini_graph_smoke"

    @classmethod
    def from_env(cls) -> "LcMiniGraphSmokeConfig":
        return cls(
            enabled=os.getenv(ENABLE_LC_MINI_SMOKE_ENV) == "1",
            lc_file_path=os.getenv(LC_FILE_PATH_ENV),
        )


@dataclass
class LcMiniGraphSmokeReport:
    __test__: ClassVar[bool] = False

    enabled: bool
    skipped: bool
    skip_reason: str | None
    working_dir: str | None
    workspace: str
    graph_storage_type: str
    source: str
    source_us_count: int
    source_text_unit_count: int
    selected_chunk_count: int
    selected_entity_count: int
    selected_relationship_count: int
    covered_domains: list[str]
    covered_sections: list[str]
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
    dangling_relationship_count: int
    confirmed_count: int
    review_required_written: bool
    info_only_written: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommended_next_step: str = ""


@dataclass(frozen=True)
class LcMiniBuildResult:
    __test__: ClassVar[bool] = False

    payload: DslKgPayload
    source_path: str
    source_us_count: int
    first_us_id: str | None
    last_us_id: str | None
    source_text_unit_count: int
    unknown_section_count: int
    risks: list[str]


@dataclass(frozen=True)
class LcMiniCandidateSpec:
    candidate_id: str
    source_entity_name: str
    source_entity_type: str
    target_entity_name: str
    target_entity_type: str
    relation_type: str
    domain_code: str
    section_type: str
    evidence_term: str


@dataclass(frozen=True)
class LcMiniContext:
    text_unit_id: str
    content: str
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str
    source_span: dict[str, int]
    text_hash: str


LC_CANDIDATE_SPECS = (
    LcMiniCandidateSpec(
        candidate_id="lc-mini-workflow-handler",
        source_entity_name="Bank Default Confirmation",
        source_entity_type="TaskRule",
        target_entity_name="Current Handler",
        target_entity_type="RolePermission",
        relation_type="AssignsHandler",
        domain_code="Workflow",
        section_type="task_rule",
        evidence_term="Please confirm the default",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-mini-risk-api-eflownum",
        source_entity_name="Risk Certification API",
        source_entity_type="IntegrationEndpoint",
        target_entity_name="eflowNum",
        target_entity_type="FieldSpec",
        relation_type="CallsBackendApi",
        domain_code="Integration",
        section_type="api_desc",
        evidence_term="eflowNum",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-mini-ledger-bank-status",
        source_entity_name="Acceptable Bank Ledger Search",
        source_entity_type="ReportSpec",
        target_entity_name="Bank Status",
        target_entity_type="FieldSpec",
        relation_type="HasReportFilter",
        domain_code="MonitoringReport",
        section_type="report_rule",
        evidence_term="Bank Status",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-mini-migration-dry-run",
        source_entity_name="Historical Data Migration",
        source_entity_type="DataMigrationSpec",
        target_entity_name="dry-run",
        target_entity_type="RuleAtom",
        relation_type="HasRuleAtom",
        domain_code="DataMigrationInitialization",
        section_type="dfx_rule",
        evidence_term="dry-run",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-mini-audit-operation-log",
        source_entity_name="Acceptable Bank Audit Log",
        source_entity_type="RolePermission",
        target_entity_name="OperationLog",
        target_entity_type="RolePermission",
        relation_type="WritesOperationLog",
        domain_code="AccessAudit",
        section_type="task_rule",
        evidence_term="OperationLog",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-ledger-status-removed",
        source_entity_name="Bank Status",
        source_entity_type="FieldSpec",
        target_entity_name="Removed",
        target_entity_type="StateTransition",
        relation_type="HasStateTransition",
        domain_code="MonitoringReport",
        section_type="field_table",
        evidence_term="Removed",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-ledger-status-not-involved",
        source_entity_name="Bank Status",
        source_entity_type="FieldSpec",
        target_entity_name="Not Involved",
        target_entity_type="StateTransition",
        relation_type="HasStateTransition",
        domain_code="MonitoringReport",
        section_type="field_table",
        evidence_term="Not Involved",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-transfer-confirmation",
        source_entity_name="Transfer To",
        source_entity_type="TaskRule",
        target_entity_name="Bank Default Confirmation",
        target_entity_type="FieldSpec",
        relation_type="TransfersTask",
        domain_code="Workflow",
        section_type="task_rule",
        evidence_term="Transfer To",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-transfer-handler",
        source_entity_name="Transfer To",
        source_entity_type="TaskRule",
        target_entity_name="Current Handler",
        target_entity_type="RolePermission",
        relation_type="TransfersTask",
        domain_code="Workflow",
        section_type="task_rule",
        evidence_term="Transfer To",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-transfer-permission",
        source_entity_name="Bank Default Confirmation",
        source_entity_type="FieldSpec",
        target_entity_name="Transfer To",
        target_entity_type="TaskRule",
        relation_type="HasPermission",
        domain_code="Workflow",
        section_type="task_rule",
        evidence_term="Bank Default Confirmation",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-risk-api-rating",
        source_entity_name="Risk Certification API",
        source_entity_type="IntegrationEndpoint",
        target_entity_name="Suggested Rating",
        target_entity_type="FieldSpec",
        relation_type="CallsBackendApi",
        domain_code="Integration",
        section_type="api_desc",
        evidence_term="Suggested Rating",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-swift-internal-code",
        source_entity_name="Swift Code",
        source_entity_type="FieldSpec",
        target_entity_name="Bank Internal Code",
        target_entity_type="FieldSpec",
        relation_type="DependsOn",
        domain_code="MasterData",
        section_type="field_table",
        evidence_term="Bank Internal Code",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-migration-swift",
        source_entity_name="Historical Data Migration",
        source_entity_type="DataMigrationSpec",
        target_entity_name="Swift Code",
        target_entity_type="FieldSpec",
        relation_type="MapsSourceToTarget",
        domain_code="DataMigrationInitialization",
        section_type="migration_rule",
        evidence_term="Swift Code",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-report-reads-ledger",
        source_entity_name="Acceptable Bank Ledger Search",
        source_entity_type="ReportSpec",
        target_entity_name="Ledger",
        target_entity_type="DomainObject",
        relation_type="ReadsLedger",
        domain_code="MonitoringReport",
        section_type="report_rule",
        evidence_term="Bank Status",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-audit-log",
        source_entity_name="Acceptable Bank Audit Log",
        source_entity_type="RolePermission",
        target_entity_name="AuditLog",
        target_entity_type="RolePermission",
        relation_type="WritesAuditLog",
        domain_code="AccessAudit",
        section_type="task_rule",
        evidence_term="AuditLog",
    ),
    LcMiniCandidateSpec(
        candidate_id="lc-expanded-data-scope",
        source_entity_name="Acceptable Bank Permission Matrix",
        source_entity_type="RolePermission",
        target_entity_name="Data Scope",
        target_entity_type="RolePermission",
        relation_type="HasPermission",
        domain_code="AccessAudit",
        section_type="field_table",
        evidence_term="Data Scope",
    ),
)


def build_lc_mini_build_result(
    config: LcMiniGraphSmokeConfig | None = None,
) -> LcMiniBuildResult:
    config = config or LcMiniGraphSmokeConfig()
    source_path = resolve_lc_source_path(config)
    if source_path is None:
        raise FileNotFoundError("LC_FIXTURE_NOT_FOUND")

    content = source_path.read_text(encoding="utf-8")
    blocks = detect_us_blocks(content)
    first_us_id = blocks[0].us_id if blocks else None
    last_us_id = blocks[-1].us_id if blocks else None
    risks = _source_baseline_risks(blocks, first_us_id, last_us_id)
    dsl_result = build_minimal_pilot_dsl_result_from_us_blocks(
        blocks,
        module_code="LCAB",
    )
    ingestion_payload = build_dsl_aware_ingestion_payload(
        content,
        document_id="DOC_LCAB_001",
        dsl_result=dsl_result,
        file_path=str(source_path),
    )
    unknown_section_count = sum(
        1 for item in ingestion_payload.metadata_payload if item.section_type == "unknown"
    )
    if ingestion_payload.source_text_unit_count != EXPECTED_SOURCE_TEXT_UNIT_COUNT:
        risks.append(
            "LC source_text_unit_count is "
            f"{ingestion_payload.source_text_unit_count}, expected "
            f"{EXPECTED_SOURCE_TEXT_UNIT_COUNT}."
        )
    if unknown_section_count:
        risks.append(f"LC unknown section count is {unknown_section_count}.")

    candidate_report = _build_candidate_report(ingestion_payload)
    review_report = build_candidate_review_report(
        [
            *candidate_report.candidate_entities,
            *candidate_report.candidate_relations,
        ],
        document_id=ingestion_payload.document_id,
    )
    full_payload = build_dsl_kg_payload(
        ingestion_payload=ingestion_payload,
        candidate_extraction_report=candidate_report,
        candidate_review_report=review_report,
    )
    mini_payload = _build_lc_mini_subset_payload(
        full_payload,
        source_path=str(source_path),
        source_us_count=len(blocks),
        source_text_unit_count=ingestion_payload.source_text_unit_count,
        unknown_section_count=unknown_section_count,
        risks=risks,
        max_chunks=config.max_chunks,
        max_entities=config.max_entities,
        max_relationships=config.max_relationships,
    )
    return LcMiniBuildResult(
        payload=mini_payload,
        source_path=str(source_path),
        source_us_count=len(blocks),
        first_us_id=first_us_id,
        last_us_id=last_us_id,
        source_text_unit_count=ingestion_payload.source_text_unit_count,
        unknown_section_count=unknown_section_count,
        risks=risks,
    )


def build_lc_mini_kg_payload(
    config: LcMiniGraphSmokeConfig | None = None,
) -> DslKgPayload:
    return build_lc_mini_build_result(config).payload


def build_lc_mini_custom_kg_input(
    config: LcMiniGraphSmokeConfig | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return to_lightrag_custom_kg_input(build_lc_mini_kg_payload(config))


def build_lc_subset_kg_payload(
    *,
    max_chunks: int = 15,
    max_entities: int = 30,
    max_relationships: int = 20,
) -> DslKgPayload:
    return build_lc_mini_kg_payload(
        LcMiniGraphSmokeConfig(
            max_chunks=max_chunks,
            max_entities=max_entities,
            max_relationships=max_relationships,
        )
    )


def run_lc_subset_graph_smoke(
    *,
    max_chunks: int = 15,
    max_entities: int = 30,
    max_relationships: int = 20,
    enabled: bool | None = None,
) -> LcMiniGraphSmokeReport:
    config = LcMiniGraphSmokeConfig.from_env()
    config.enabled = (
        os.getenv(ENABLE_LC_SUBSET_SMOKE_ENV) == "1"
        if enabled is None
        else enabled
    )
    config.max_chunks = max_chunks
    config.max_entities = max_entities
    config.max_relationships = max_relationships
    return run_lc_mini_graph_smoke(config=config)


def apply_lc_endpoint_closure(
    payload: DslKgPayload,
    candidate_relationships: list[KgRelationship],
    *,
    max_entities: int,
    max_relationships: int,
) -> tuple[list[KgEntity], list[KgRelationship], int]:
    entity_by_name = {entity.entity_name: entity for entity in payload.entities}
    selected_entities: list[KgEntity] = []
    selected_relationships: list[KgRelationship] = []
    dropped_relationships = 0

    for relationship in candidate_relationships[:max_relationships]:
        endpoints = [
            entity_by_name.get(relationship.src_id),
            entity_by_name.get(relationship.tgt_id),
        ]
        if any(entity is None for entity in endpoints):
            dropped_relationships += 1
            continue

        prospective = list(selected_entities)
        for entity in endpoints:
            if entity is not None and entity.entity_name not in {
                item.entity_name for item in prospective
            }:
                prospective.append(entity)
        if len(prospective) > max_entities:
            dropped_relationships += 1
            continue
        selected_entities = prospective
        selected_relationships.append(relationship)

    selected_names = {entity.entity_name for entity in selected_entities}
    dangling_count = sum(
        1
        for relationship in selected_relationships
        if relationship.src_id not in selected_names
        or relationship.tgt_id not in selected_names
    )
    if dangling_count:
        selected_relationships = [
            relationship
            for relationship in selected_relationships
            if relationship.src_id in selected_names
            and relationship.tgt_id in selected_names
        ]
    return selected_entities, selected_relationships, dropped_relationships + dangling_count


def resolve_lc_source_path(
    config: LcMiniGraphSmokeConfig | None = None,
) -> Path | None:
    config = config or LcMiniGraphSmokeConfig()
    if config.lc_file_path:
        path = Path(config.lc_file_path)
        return path if path.exists() else None
    candidates: list[Path] = []
    candidates.extend([DEFAULT_LC_FILE, FALLBACK_LC_FIXTURE])
    for path in candidates:
        if path.exists():
            return path
    return None


def run_lc_mini_graph_smoke(
    *,
    config: LcMiniGraphSmokeConfig | None = None,
) -> LcMiniGraphSmokeReport:
    config = config or LcMiniGraphSmokeConfig.from_env()
    started = time.monotonic()
    try:
        build_result = build_lc_mini_build_result(config)
    except FileNotFoundError:
        return _missing_file_report(config, started)

    payload = build_result.payload
    custom_kg = to_lightrag_custom_kg_input(payload)
    sidecar_records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace=config.namespace,
    )
    alignment = validate_graph_insert_sidecar_alignment(custom_kg, sidecar_records)
    guard_issues = _custom_kg_guard_issues(payload, custom_kg)
    counts = _status_counts(payload)
    dangling_count = _dangling_relationship_count(custom_kg)
    forbidden_count = sum(
        1 for item in payload.relationships if item.keywords in FORBIDDEN_RELATION_TYPES
    )

    base_report = _base_report(
        config,
        payload=payload,
        build_result=build_result,
        sidecar_record_count=len(sidecar_records),
        sidecar_alignment_passed=alignment.pass_status == "PASS",
        forbidden_relation_count=forbidden_count,
        dangling_relationship_count=dangling_count,
        confirmed_count=counts["confirmed"],
        review_required_written=counts["review_required"] > 0,
        info_only_written=counts["info_only"] > 0,
        started=started,
    )

    if not config.enabled:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="Feature flag enable_dsl_aware_lc_mini_graph_smoke is disabled.",
            elapsed_ms=_elapsed_ms(started),
            recommended_next_step="ENABLE_FEATURE_FLAG_TO_TEST_GRAPH_WRITE",
        )
    if not config.force_local_graph_storage or config.local_graph_storage != SMOKE_GRAPH_STORAGE:
        return _blocked_report(
            base_report,
            "LC_MINI_GRAPH_UNSUPPORTED",
            "LC mini smoke requires local NetworkXStorage.",
            "FIX_GRAPH_STORAGE_CONFIG",
            started,
        )
    if config.allow_neo4j:
        return _blocked_report(
            base_report,
            "NEO4J_FORBIDDEN",
            "LC mini smoke must not allow Neo4j.",
            "DO_NOT_WRITE_GRAPH",
            started,
        )
    if not config.use_fake_embedding or not config.use_fake_llm:
        return _blocked_report(
            base_report,
            "FAKE_MODEL_REQUIRED",
            "LC mini smoke must use fake embedding and fake LLM.",
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
                _issue(
                    "SIDECAR_ALIGNMENT_FAIL",
                    "LC mini sidecar alignment failed.",
                )
            ],
            recommended_next_step="FIX_SIDECAR_ALIGNMENT",
        )
    if dangling_count:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="DANGLING_RELATIONSHIP_BLOCKED",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "DANGLING_RELATIONSHIP_BLOCKED",
                    "LC mini relationship endpoint is missing.",
                )
            ],
            recommended_next_step="FIX_ENDPOINT_CLOSURE",
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
            "LC mini smoke requires disposable temp working_dir.",
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
            issues=[_issue("TIMEOUT", "LC mini graph smoke timed out.")],
            recommended_next_step="FIX_CUSTOM_KG_TIMEOUT",
        )
    except Exception as exc:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="LC_MINI_GRAPH_UNSUPPORTED",
            graph_write_attempted=True,
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "LC_MINI_GRAPH_UNSUPPORTED",
                    f"{type(exc).__name__}: {exc}",
                )
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
            "CONSIDER_LC_GRAPH_SUBSET_RETRIEVAL_DRY_RUN"
            if result["cleanup_passed"]
            else "FIX_GRAPH_CLEANUP"
        ),
    )


def serialize_lc_mini_graph_smoke_report(
    report: LcMiniGraphSmokeReport,
) -> dict[str, Any]:
    return asdict(report)


def _build_lc_mini_subset_payload(
    full_payload: DslKgPayload,
    *,
    source_path: str,
    source_us_count: int,
    source_text_unit_count: int,
    unknown_section_count: int,
    risks: list[str],
    max_chunks: int,
    max_entities: int,
    max_relationships: int,
) -> DslKgPayload:
    selected_relationships = _select_lc_mini_relationships(
        full_payload,
        max_relationships,
    )
    selected_entities, selected_relationships, dangling_count = apply_lc_endpoint_closure(
        full_payload,
        selected_relationships,
        max_entities=max_entities,
        max_relationships=max_relationships,
    )
    if dangling_count:
        risks.append(f"Endpoint closure dropped {dangling_count} LC mini relationships.")

    selected_source_ids: list[str] = []
    for relationship in selected_relationships:
        _append_unique(selected_source_ids, relationship.source_id)
    for entity in selected_entities:
        _append_unique(selected_source_ids, entity.source_id)
    if len(selected_source_ids) > max_chunks:
        risks.append(
            f"LC mini source ids truncated from {len(selected_source_ids)} to {max_chunks}."
        )
        selected_source_ids = selected_source_ids[:max_chunks]

    chunk_by_id = {chunk.source_id: chunk for chunk in full_payload.chunks}
    selected_chunks = [
        chunk_by_id[source_id]
        for source_id in selected_source_ids
        if source_id in chunk_by_id
    ]
    selected_chunk_ids = {chunk.source_id for chunk in selected_chunks}
    selected_entities = [
        entity for entity in selected_entities if entity.source_id in selected_chunk_ids
    ][:max_entities]
    selected_entity_names = {entity.entity_name for entity in selected_entities}
    selected_relationships = [
        relationship
        for relationship in selected_relationships
        if relationship.source_id in selected_chunk_ids
        and relationship.src_id in selected_entity_names
        and relationship.tgt_id in selected_entity_names
    ][:max_relationships]
    covered_domains = _covered_values(selected_entities, selected_relationships, "domainCode")
    covered_sections = _covered_values(selected_entities, selected_relationships, "sectionType")

    return DslKgPayload(
        chunks=selected_chunks,
        entities=selected_entities,
        relationships=selected_relationships,
        metadata={
            **full_payload.metadata,
            "source": LC_SOURCE_NAME,
            "sourcePath": source_path,
            "miniSubset": True,
            "sourceUsCount": source_us_count,
            "sourceTextUnitCount": source_text_unit_count,
            "unknownSectionCount": unknown_section_count,
            "coveredDomains": covered_domains,
            "coveredSections": covered_sections,
            "maxChunks": max_chunks,
            "maxEntities": max_entities,
            "maxRelationships": max_relationships,
        },
        issues=list(full_payload.issues),
        summary={
            "source": LC_SOURCE_NAME,
            "source_us_count": source_us_count,
            "source_text_unit_count": source_text_unit_count,
            "selected_chunk_count": len(selected_chunks),
            "selected_entity_count": len(selected_entities),
            "selected_relationship_count": len(selected_relationships),
            "covered_domains": covered_domains,
            "covered_sections": covered_sections,
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


def _build_candidate_report(payload) -> CandidateExtractionReport:
    entities: list[CandidateEntity] = []
    relations: list[CandidateRelation] = []
    for spec in LC_CANDIDATE_SPECS:
        context = _find_context(
            payload,
            domain_code=spec.domain_code,
            section_type=spec.section_type,
            term=spec.evidence_term,
        )
        entities.extend(
            [
                _entity(
                    f"{spec.candidate_id}-source",
                    spec.source_entity_name,
                    spec.source_entity_type,
                    context,
                    spec=spec,
                ),
                _entity(
                    f"{spec.candidate_id}-target",
                    spec.target_entity_name,
                    spec.target_entity_type,
                    context,
                    spec=spec,
                ),
            ]
        )
        relations.append(_relation(spec.candidate_id, spec, context))
    return CandidateExtractionReport(
        enabled=True,
        skipped=False,
        skip_reason=None,
        extraction_run_id="candidate-run-lc-mini",
        document_id=payload.document_id,
        sample_count=len(LC_CANDIDATE_SPECS),
        native_extract_called=False,
        live_llm_used=False,
        candidate_entity_count=len(entities),
        candidate_relation_count=len(relations),
        valid_entity_count=len(entities),
        valid_relation_count=len(relations),
        invalid_entity_count=0,
        invalid_relation_count=0,
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
        quality_summary={"candidateOnly": True, "source": LC_SOURCE_NAME},
        recommended_next_step="BUILD_CANDIDATE_REVIEW_REPORT",
        candidate_entities=entities,
        candidate_relations=relations,
    )


def _entity(
    candidate_id: str,
    entity_name: str,
    entity_type: str,
    context: LcMiniContext,
    *,
    spec: LcMiniCandidateSpec,
) -> CandidateEntity:
    return CandidateEntity(
        candidate_id=candidate_id,
        entity_name=entity_name,
        entity_type=entity_type,
        description=f"{entity_name} is grounded in LC source evidence.",
        domain_code=context.domain_code or spec.domain_code,
        feature_key=context.feature_key,
        source_us_id=context.source_us_id,
        source_text_unit_id=context.text_unit_id,
        section_type=context.section_type,
        source_span=context.source_span,
        text_hash=context.text_hash,
        evidence_text=context.content,
        extraction_run_id="candidate-run-lc-mini",
        knowledge_status=KNOWLEDGE_STATUS_CANDIDATE,
        validation_status=VALIDATION_VALID,
        confidence_score=0.95,
        raw={
            "allowedEntityTypes": [entity_type],
            "allowedRelationTypes": [spec.relation_type],
        },
    )


def _relation(
    candidate_id: str,
    spec: LcMiniCandidateSpec,
    context: LcMiniContext,
) -> CandidateRelation:
    return CandidateRelation(
        candidate_id=candidate_id,
        source_entity_name=spec.source_entity_name,
        target_entity_name=spec.target_entity_name,
        relation_type=spec.relation_type,
        relationship_keywords=spec.relation_type,
        description=(
            f"{spec.source_entity_name} {spec.relation_type} "
            f"{spec.target_entity_name}."
        ),
        domain_code=context.domain_code or spec.domain_code,
        feature_key=context.feature_key,
        source_us_id=context.source_us_id,
        source_text_unit_id=context.text_unit_id,
        section_type=context.section_type,
        source_span=context.source_span,
        text_hash=context.text_hash,
        evidence_text=context.content,
        extraction_run_id="candidate-run-lc-mini",
        knowledge_status=KNOWLEDGE_STATUS_CANDIDATE,
        validation_status=VALIDATION_VALID,
        confidence_score=0.95,
        raw={"allowedRelationTypes": [spec.relation_type]},
    )


def _find_context(
    payload,
    *,
    domain_code: str,
    section_type: str,
    term: str,
) -> LcMiniContext:
    vector_by_chunk = {item.chunk_id: item for item in payload.vector_payload}
    lowered_term = term.lower()
    for item in payload.metadata_payload:
        if item.domain_code != domain_code or item.section_type != section_type:
            continue
        vector = vector_by_chunk.get(item.vector_chunk_id)
        if vector is None or lowered_term not in vector.content.lower():
            continue
        return LcMiniContext(
            text_unit_id=item.text_unit_id,
            content=vector.content,
            source_us_id=item.source_us_id,
            feature_key=item.feature_key,
            domain_code=item.domain_code,
            section_type=item.section_type,
            source_span=item.source_span,
            text_hash=item.text_hash,
        )
    raise ValueError(f"LC mini evidence context not found: {domain_code}/{section_type}/{term}")


def _select_lc_mini_relationships(
    payload: DslKgPayload,
    max_relationships: int,
) -> list[KgRelationship]:
    selected: list[KgRelationship] = []
    for spec in LC_CANDIDATE_SPECS:
        for relationship in payload.relationships:
            if (
                relationship.src_id == spec.source_entity_name
                and relationship.tgt_id == spec.target_entity_name
                and relationship.keywords == spec.relation_type
            ):
                selected.append(relationship)
                break
        if len(selected) >= max_relationships:
            break
    if len(selected) < max_relationships:
        for relationship in payload.relationships:
            if relationship.keywords not in {
                "HasVersion",
                "VersionReviewRequired",
                "VersionConflictWith",
                "Supersedes",
            }:
                continue
            if relationship in selected:
                continue
            selected.append(relationship)
            if len(selected) >= max_relationships:
                break
    return selected[:max_relationships]


def _custom_kg_guard_issues(
    payload: DslKgPayload,
    custom_kg: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    chunk_source_ids = {item["source_id"] for item in custom_kg["chunks"]}
    entity_names = {item["entity_name"] for item in custom_kg["entities"]}
    for chunk in custom_kg["chunks"]:
        content = str(chunk["content"])
        if "DSL_CONTEXT" in content or '"dslVersion"' in content:
            issues.append(
                _issue(
                    "DSL_CONTEXT_CONTENT_BLOCKED",
                    "LC mini custom_kg chunk contains DSL context material.",
                )
            )
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
            issues.append(_issue("FORBIDDEN_RELATION_BLOCKED", "Forbidden relation found."))
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


def _dangling_relationship_count(custom_kg: dict[str, list[dict[str, Any]]]) -> int:
    entity_names = {item["entity_name"] for item in custom_kg["entities"]}
    return sum(
        1
        for relationship in custom_kg["relationships"]
        if relationship["src_id"] not in entity_names
        or relationship["tgt_id"] not in entity_names
    )


def _base_report(
    config: LcMiniGraphSmokeConfig,
    *,
    payload: DslKgPayload,
    build_result: LcMiniBuildResult,
    sidecar_record_count: int,
    sidecar_alignment_passed: bool,
    forbidden_relation_count: int,
    dangling_relationship_count: int,
    confirmed_count: int,
    review_required_written: bool,
    info_only_written: bool,
    started: float,
) -> LcMiniGraphSmokeReport:
    return LcMiniGraphSmokeReport(
        enabled=config.enabled,
        skipped=True,
        skip_reason=None,
        working_dir=None,
        workspace=config.workspace,
        graph_storage_type=config.local_graph_storage,
        source=LC_SOURCE_NAME,
        source_us_count=build_result.source_us_count,
        source_text_unit_count=build_result.source_text_unit_count,
        selected_chunk_count=len(payload.chunks),
        selected_entity_count=len(payload.entities),
        selected_relationship_count=len(payload.relationships),
        covered_domains=list(payload.metadata.get("coveredDomains") or []),
        covered_sections=list(payload.metadata.get("coveredSections") or []),
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
        dangling_relationship_count=dangling_relationship_count,
        confirmed_count=confirmed_count,
        review_required_written=review_required_written,
        info_only_written=info_only_written,
        issues=[],
        risks=list(build_result.risks),
        recommended_next_step="",
    )


def _missing_file_report(
    config: LcMiniGraphSmokeConfig,
    started: float,
) -> LcMiniGraphSmokeReport:
    return LcMiniGraphSmokeReport(
        enabled=config.enabled,
        skipped=True,
        skip_reason="LC_FIXTURE_NOT_FOUND",
        working_dir=None,
        workspace=config.workspace,
        graph_storage_type=config.local_graph_storage,
        source=LC_SOURCE_NAME,
        source_us_count=0,
        source_text_unit_count=0,
        selected_chunk_count=0,
        selected_entity_count=0,
        selected_relationship_count=0,
        covered_domains=[],
        covered_sections=[],
        sidecar_record_count=0,
        sidecar_alignment_passed=False,
        ainsert_custom_kg_called=False,
        graph_write_attempted=False,
        graph_write_succeeded=False,
        neo4j_connected=False,
        production_namespace_blocked=False,
        fake_embedding_used=config.use_fake_embedding,
        fake_llm_used=config.use_fake_llm,
        cleanup_passed=True,
        elapsed_ms=_elapsed_ms(started),
        forbidden_relation_count=0,
        dangling_relationship_count=0,
        confirmed_count=0,
        review_required_written=False,
        info_only_written=False,
        issues=[
            _issue(
                "LC_FIXTURE_NOT_FOUND",
                "LC source file was not found; graph write was not attempted.",
            )
        ],
        risks=[],
        recommended_next_step="PROVIDE_LC_SOURCE_FIXTURE",
    )


def _blocked_report(
    base_report: LcMiniGraphSmokeReport,
    code: str,
    message: str,
    recommended_next_step: str,
    started: float,
) -> LcMiniGraphSmokeReport:
    return _replace_report(
        base_report,
        skipped=True,
        skip_reason=code,
        elapsed_ms=_elapsed_ms(started),
        issues=[_issue(code, message)],
        recommended_next_step=recommended_next_step,
    )


def _replace_report(
    report: LcMiniGraphSmokeReport,
    **changes: Any,
) -> LcMiniGraphSmokeReport:
    data = asdict(report)
    data.update(changes)
    return LcMiniGraphSmokeReport(**data)


def _source_baseline_risks(
    blocks: list[Any],
    first_us_id: str | None,
    last_us_id: str | None,
) -> list[str]:
    risks: list[str] = []
    if len(blocks) != EXPECTED_SOURCE_US_COUNT:
        risks.append(f"LC source_us_count is {len(blocks)}, expected 66.")
    if first_us_id != EXPECTED_FIRST_US_ID:
        risks.append(f"LC first US is {first_us_id}, expected {EXPECTED_FIRST_US_ID}.")
    if last_us_id != EXPECTED_LAST_US_ID:
        risks.append(f"LC last US is {last_us_id}, expected {EXPECTED_LAST_US_ID}.")
    return risks


def _covered_values(
    entities: list[KgEntity],
    relationships: list[KgRelationship],
    key: str,
) -> list[str]:
    values = {
        str(value)
        for value in [
            *(item.metadata.get(key) for item in entities),
            *(item.metadata.get(key) for item in relationships),
        ]
        if value
    }
    return sorted(values)


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": message}


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


__all__ = [
    "ENABLE_LC_MINI_SMOKE_ENV",
    "ENABLE_LC_SUBSET_SMOKE_ENV",
    "LC_FILE_PATH_ENV",
    "LC_SOURCE_NAME",
    "LcMiniGraphSmokeConfig",
    "LcMiniGraphSmokeReport",
    "apply_lc_endpoint_closure",
    "build_lc_mini_build_result",
    "build_lc_mini_custom_kg_input",
    "build_lc_mini_kg_payload",
    "build_lc_subset_kg_payload",
    "resolve_lc_source_path",
    "run_lc_mini_graph_smoke",
    "run_lc_subset_graph_smoke",
    "serialize_lc_mini_graph_smoke_report",
]
