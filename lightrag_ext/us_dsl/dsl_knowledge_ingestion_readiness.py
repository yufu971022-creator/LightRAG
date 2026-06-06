from __future__ import annotations

from collections import Counter
from typing import Any

from .domain_registry import default_domain_registry
from .dsl_knowledge_ingestion_policy import PreparedIngestionPayload, prepare_policy_approved_ingestion_payload
from .dsl_knowledge_ingestion_types import (
    DslKnowledgeIngestionConfig,
    DslKnowledgeIngestionReport,
    serialize_dsl_knowledge_ingestion_report,
)
from .kg_payload_types import DslKgPayload
from .kg_real_graph_smoke import SMOKE_GRAPH_STORAGE
from .module_ingestion_registry import build_module_ingestion_payload
from .version_issue_triage import build_version_issue_triage_report
from .version_relation_builder import extract_versioned_semantic_objects


def run_ingestion_readiness_gate(
    *,
    source_path: str | None = None,
    dsl_payload: DslKgPayload | None = None,
    ingestion_payload=None,
    module_name: str | None = None,
    config: DslKnowledgeIngestionConfig | None = None,
) -> DslKnowledgeIngestionReport:
    del ingestion_payload
    config = config or DslKnowledgeIngestionConfig()
    if not config.enabled:
        return _empty_report(
            config,
            stage="readiness",
            skipped=True,
            skip_reason="Feature flag enable_dsl_aware_knowledge_ingestion is disabled.",
            recommended_next_step="ENABLE_DSL_KNOWLEDGE_INGESTION",
        )
    if not _safe_namespace(config.namespace):
        return _empty_report(
            config,
            stage="readiness",
            skipped=True,
            skip_reason="PRODUCTION_NAMESPACE_BLOCKED",
            issues=[_issue("PRODUCTION_NAMESPACE_BLOCKED")],
            recommended_next_step="FIX_READINESS_GATE",
        )

    try:
        source_result = _build_source(
            config=config,
            dsl_payload=dsl_payload,
            source_path=source_path,
            module_name=module_name,
        )
    except Exception as exc:
        return _empty_report(
            config,
            stage="readiness",
            skipped=True,
            skip_reason="UNSUPPORTED_SOURCE_TO_KG_PAYLOAD",
            issues=[
                _issue(
                    "UNSUPPORTED_SOURCE_TO_KG_PAYLOAD",
                    message=f"{type(exc).__name__}: {exc}",
                )
            ],
            recommended_next_step="FIX_READINESS_GATE",
        )
    payload = source_result["payload"]
    prepared = prepare_policy_approved_ingestion_payload(
        payload,
        namespace=config.namespace,
        registry=default_domain_registry(),
    )
    triage = build_version_issue_triage_report(
        extract_versioned_semantic_objects(kg_payload=payload)
    )
    domain_distribution = _domain_distribution(payload)
    version_policy_ready = (
        triage.pass_status == "PASS"
        and triage.unsafe_supersedes_blocked_count == 0
        and triage.review_required_after_count <= triage.review_required_before_count
    )
    ready = (
        version_policy_ready
        and prepared.sidecar_alignment_passed
        and prepared.endpoint_closure_passed
        and prepared.forbidden_relation_count == 0
        and prepared.idempotency_key_duplicate_count == 0
        and prepared.rollback_plan_present
        and prepared.approved_entity_count > 0
    )
    issues = list(prepared.issues)
    if not version_policy_ready:
        issues.append(_issue("VERSION_POLICY_NOT_READY"))
    if not prepared.endpoint_closure_passed:
        issues.append(_issue("ENDPOINT_CLOSURE_FAILED"))
    if prepared.forbidden_relation_count:
        issues.append(_issue("FORBIDDEN_RELATION_IN_CUSTOM_KG"))
    if prepared.idempotency_key_duplicate_count:
        issues.append(_issue("DUPLICATE_IDEMPOTENCY_KEY"))
    if not prepared.rollback_plan_present:
        issues.append(_issue("ROLLBACK_PLAN_MISSING"))

    report = _report_from_prepared(
        config,
        prepared=prepared,
        stage="readiness",
        ready_to_write=ready,
        source=str(source_result.get("source") or config.source or config.source_path or ""),
        module_name=source_result.get("module_name") or module_name or config.module_name,
        source_us_count=int(source_result.get("source_us_count") or 0),
        source_text_unit_count=int(source_result.get("source_text_unit_count") or 0),
        domain_distribution=domain_distribution,
        version_policy_ready=version_policy_ready,
        version_review_required_before=triage.review_required_before_count,
        version_review_required_after=triage.review_required_after_count,
        unsafe_supersedes_blocked_count=triage.unsafe_supersedes_blocked_count,
        source_order_supersedes_count=0,
        kg_payload_chunk_count=len(payload.chunks),
        kg_payload_entity_count=len(payload.entities),
        kg_payload_relationship_count=len(payload.relationships),
        issues=issues,
        recommended_next_step="RUN_CANARY_TEST_GRAPH_INGESTION" if ready else "FIX_READINESS_GATE",
    )
    return report


def build_readiness_artifacts(
    *,
    config: DslKnowledgeIngestionConfig,
    dsl_payload: DslKgPayload | None = None,
    source_path: str | None = None,
    module_name: str | None = None,
) -> tuple[DslKgPayload, PreparedIngestionPayload, DslKnowledgeIngestionReport]:
    source_result = _build_source(
        config=config,
        dsl_payload=dsl_payload,
        source_path=source_path,
        module_name=module_name,
    )
    report = run_ingestion_readiness_gate(
        dsl_payload=source_result["payload"],
        config=config,
        source_path=source_path,
        module_name=source_result.get("module_name") or module_name,
    )
    prepared = prepare_policy_approved_ingestion_payload(
        source_result["payload"],
        namespace=config.namespace,
        registry=default_domain_registry(),
    )
    return source_result["payload"], prepared, report


def _build_source(
    *,
    config: DslKnowledgeIngestionConfig,
    dsl_payload: DslKgPayload | None,
    source_path: str | None = None,
    module_name: str | None = None,
) -> dict[str, Any]:
    if dsl_payload is not None:
        return {
            "payload": dsl_payload,
            "source": config.source or source_path,
            "source_us_count": int(dsl_payload.metadata.get("sourceUsCount") or 0),
            "source_text_unit_count": int(dsl_payload.metadata.get("sourceTextUnitCount") or 0),
            "module_name": module_name or config.module_name,
        }
    result = build_module_ingestion_payload(
        module_name=module_name or config.module_name,
        source_path=source_path or config.source_path,
        max_chunks=config.max_chunks,
        max_entities=config.max_entities,
        max_relationships=config.max_relationships,
    )
    return {
        "payload": result.payload,
        "source": result.source,
        "source_us_count": result.source_us_count,
        "source_text_unit_count": result.source_text_unit_count,
        "module_name": result.module_name,
    }


def _report_from_prepared(
    config: DslKnowledgeIngestionConfig,
    *,
    prepared: PreparedIngestionPayload,
    stage: str,
    ready_to_write: bool,
    source: str | None,
    module_name: str | None,
    source_us_count: int,
    source_text_unit_count: int,
    domain_distribution: dict[str, int],
    version_policy_ready: bool,
    version_review_required_before: int,
    version_review_required_after: int,
    unsafe_supersedes_blocked_count: int,
    source_order_supersedes_count: int,
    kg_payload_chunk_count: int,
    kg_payload_entity_count: int,
    kg_payload_relationship_count: int,
    issues: list[dict[str, Any]],
    recommended_next_step: str,
) -> DslKnowledgeIngestionReport:
    custom_kg = prepared.custom_kg_input
    batch_count = _batch_count(custom_kg, config.batch_size)
    return DslKnowledgeIngestionReport(
        enabled=config.enabled,
        skipped=False,
        skip_reason=None,
        stage=stage,
        ready_to_write=ready_to_write,
        canary_prerequisite_passed=False,
        module_name=module_name,
        source=source,
        namespace=config.namespace,
        working_dir=config.working_dir,
        source_us_count=source_us_count,
        source_text_unit_count=source_text_unit_count,
        domain_distribution=domain_distribution,
        version_policy_ready=version_policy_ready,
        version_review_required_before=version_review_required_before,
        version_review_required_after=version_review_required_after,
        unsafe_supersedes_blocked_count=unsafe_supersedes_blocked_count,
        source_order_supersedes_count=source_order_supersedes_count,
        kg_payload_chunk_count=kg_payload_chunk_count,
        kg_payload_entity_count=kg_payload_entity_count,
        kg_payload_relationship_count=kg_payload_relationship_count,
        approved_chunk_count=len(prepared.approved_payload.chunks),
        approved_entity_count=prepared.approved_entity_count,
        approved_relationship_count=prepared.approved_relationship_count,
        blocked_object_count=prepared.blocked_object_count,
        blocked_reason_occurrence_count=prepared.blocked_reason_occurrence_count,
        blocked_count=prepared.blocked_count,
        block_reason_distribution=prepared.block_reason_distribution,
        custom_kg_chunk_count=len(custom_kg.get("chunks", [])),
        custom_kg_entity_count=len(custom_kg.get("entities", [])),
        custom_kg_relationship_count=len(custom_kg.get("relationships", [])),
        dropped_relationship_due_to_endpoint_count=(
            prepared.dropped_relationship_due_to_endpoint_count
        ),
        truncated_entity_count=0,
        truncated_relationship_count=0,
        sidecar_record_count=len(prepared.sidecar_records),
        sidecar_alignment_passed=prepared.sidecar_alignment_passed,
        endpoint_closure_passed=prepared.endpoint_closure_passed,
        dangling_relationship_count=prepared.dangling_relationship_count,
        forbidden_relation_count=prepared.forbidden_relation_count,
        idempotency_key_duplicate_count=prepared.idempotency_key_duplicate_count,
        batch_count=batch_count,
        failed_batch_count=0,
        ainsert_custom_kg_called=False,
        graph_write_succeeded=False,
        neo4j_connected=False,
        production_write=False,
        formal_graph_written=False,
        cleanup_passed=True,
        rollback_passed=True,
        graph_storage_type=SMOKE_GRAPH_STORAGE,
        cleanup_after_run=config.cleanup_after_run,
        rollback_after_run=config.rollback_after_run,
        rollback_plan_present=prepared.rollback_plan_present,
        rollback_key_count=prepared.rollback_key_count,
        rollback_strategy=prepared.rollback_strategy,
        idempotency_passed=prepared.idempotency_key_duplicate_count == 0,
        evidence_missing_count=prepared.evidence_missing_count,
        version_review_required_blocked_count=prepared.version_review_required_blocked_count,
        review_required_blocked_count=prepared.review_required_blocked_count,
        info_only_blocked_count=prepared.info_only_blocked_count,
        invalid_relation_blocked_count=prepared.invalid_relation_blocked_count,
        forbidden_relation_blocked_count=prepared.forbidden_relation_blocked_count,
        dangling_relationship_blocked_count=prepared.dangling_relationship_blocked_count,
        issues=issues,
        risks=list(prepared.risks),
        how_to_cleanup=None,
        recommended_next_step=recommended_next_step,
    )


def _empty_report(
    config: DslKnowledgeIngestionConfig,
    *,
    stage: str,
    skipped: bool,
    skip_reason: str | None,
    issues: list[dict[str, Any]] | None = None,
    recommended_next_step: str,
) -> DslKnowledgeIngestionReport:
    return DslKnowledgeIngestionReport(
        enabled=config.enabled,
        skipped=skipped,
        skip_reason=skip_reason,
        stage=stage,
        ready_to_write=False,
        canary_prerequisite_passed=False,
        module_name=config.module_name,
        source=config.source or config.source_path,
        namespace=config.namespace,
        working_dir=config.working_dir,
        source_us_count=0,
        source_text_unit_count=0,
        domain_distribution={},
        version_policy_ready=False,
        version_review_required_before=0,
        version_review_required_after=0,
        unsafe_supersedes_blocked_count=0,
        source_order_supersedes_count=0,
        kg_payload_chunk_count=0,
        kg_payload_entity_count=0,
        kg_payload_relationship_count=0,
        approved_chunk_count=0,
        approved_entity_count=0,
        approved_relationship_count=0,
        blocked_object_count=0,
        blocked_reason_occurrence_count=0,
        blocked_count=0,
        block_reason_distribution={},
        custom_kg_chunk_count=0,
        custom_kg_entity_count=0,
        custom_kg_relationship_count=0,
        dropped_relationship_due_to_endpoint_count=0,
        truncated_entity_count=0,
        truncated_relationship_count=0,
        sidecar_record_count=0,
        sidecar_alignment_passed=False,
        endpoint_closure_passed=False,
        dangling_relationship_count=0,
        forbidden_relation_count=0,
        idempotency_key_duplicate_count=0,
        batch_count=0,
        failed_batch_count=0,
        ainsert_custom_kg_called=False,
        graph_write_succeeded=False,
        neo4j_connected=False,
        production_write=False,
        formal_graph_written=False,
        cleanup_passed=True,
        rollback_passed=True,
        graph_storage_type=SMOKE_GRAPH_STORAGE,
        cleanup_after_run=config.cleanup_after_run,
        rollback_after_run=config.rollback_after_run,
        rollback_plan_present=False,
        rollback_key_count=0,
        rollback_strategy=None,
        idempotency_passed=False,
        evidence_missing_count=0,
        version_review_required_blocked_count=0,
        review_required_blocked_count=0,
        info_only_blocked_count=0,
        invalid_relation_blocked_count=0,
        forbidden_relation_blocked_count=0,
        dangling_relationship_blocked_count=0,
        issues=issues or [],
        risks=[],
        how_to_cleanup=None,
        recommended_next_step=recommended_next_step,
    )


def _domain_distribution(payload: DslKgPayload) -> dict[str, int]:
    registry = default_domain_registry()
    counter: Counter[str] = Counter()
    for item in [*payload.entities, *payload.relationships]:
        counter[registry.normalize_domain(item.metadata.get("domainCode"))] += 1
    return dict(counter)


def _batch_count(custom_kg: dict[str, list[dict[str, Any]]], batch_size: int) -> int:
    object_count = len(custom_kg.get("entities", [])) + len(custom_kg.get("relationships", []))
    if object_count == 0:
        return 0
    return max(1, (object_count + max(1, batch_size) - 1) // max(1, batch_size))


def _safe_namespace(namespace: str) -> bool:
    lowered = namespace.lower()
    return ("test" in lowered or "dsl_test" in lowered) and lowered not in {
        "prod",
        "production",
        "main",
        "default",
    }


def _issue(code: str, *, message: str | None = None) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": message or code}


__all__ = [
    "build_readiness_artifacts",
    "run_ingestion_readiness_gate",
    "serialize_dsl_knowledge_ingestion_report",
]
