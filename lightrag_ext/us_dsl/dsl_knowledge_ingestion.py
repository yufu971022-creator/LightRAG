from __future__ import annotations

from dataclasses import replace
from typing import Any

from .dsl_knowledge_ingestion_readiness import (
    build_readiness_artifacts,
    run_ingestion_readiness_gate,
)
from .dsl_knowledge_ingestion_types import (
    DslKnowledgeIngestionConfig,
    DslKnowledgeIngestionReport,
    serialize_dsl_knowledge_ingestion_report,
)
from .dsl_knowledge_ingestion_writer import (
    WriteResult,
    write_custom_kg_batches_to_lightrag,
)
from .kg_real_graph_smoke import SMOKE_GRAPH_STORAGE


def run_dsl_knowledge_ingestion(
    *,
    source_path: str | None = None,
    dsl_payload=None,
    ingestion_payload=None,
    module_name: str | None = None,
    config: DslKnowledgeIngestionConfig | None = None,
) -> DslKnowledgeIngestionReport:
    del ingestion_payload
    config = config or DslKnowledgeIngestionConfig.from_env()
    mode = config.ingest_mode.lower()
    if mode == "readiness":
        return run_ingestion_readiness_gate(
            source_path=source_path,
            dsl_payload=dsl_payload,
            module_name=module_name,
            config=config,
        )
    if mode == "canary":
        readiness = run_ingestion_readiness_gate(
            source_path=source_path,
            dsl_payload=dsl_payload,
            module_name=module_name,
            config=_stage_config(config, "readiness"),
        )
        return run_canary_dsl_knowledge_ingestion(
            readiness,
            config=config,
            source_path=source_path,
            dsl_payload=dsl_payload,
            module_name=module_name,
        )
    if mode == "module":
        readiness = run_ingestion_readiness_gate(
            source_path=source_path,
            dsl_payload=dsl_payload,
            module_name=module_name,
            config=_stage_config(config, "readiness"),
        )
        if not readiness.ready_to_write:
            return _blocked_stage_report(
                readiness,
                stage="module",
                skip_reason="READINESS_GATE_FAILED",
                recommended_next_step="FIX_READINESS_GATE",
            )
        canary = run_canary_dsl_knowledge_ingestion(
            readiness,
            config=config,
            source_path=source_path,
            dsl_payload=dsl_payload,
            module_name=module_name,
        )
        return run_module_level_dsl_knowledge_ingestion(
            canary,
            config=config,
            source_path=source_path,
            dsl_payload=dsl_payload,
            module_name=module_name,
        )
    return run_ingestion_readiness_gate(
        config=replace(config, enabled=False, ingest_mode="readiness")
    )


def run_canary_dsl_knowledge_ingestion(
    readiness_report: DslKnowledgeIngestionReport,
    *,
    config: DslKnowledgeIngestionConfig,
    source_path: str | None = None,
    dsl_payload=None,
    module_name: str | None = None,
) -> DslKnowledgeIngestionReport:
    if not readiness_report.ready_to_write:
        return _blocked_stage_report(
            readiness_report,
            stage="canary",
            skip_reason="READINESS_GATE_FAILED",
            recommended_next_step="FIX_READINESS_GATE",
        )
    canary_config = _canary_config(config)
    _payload, prepared, canary_readiness = build_readiness_artifacts(
        config=canary_config,
        dsl_payload=dsl_payload,
        source_path=source_path,
        module_name=module_name,
    )
    if not canary_readiness.ready_to_write:
        return _blocked_stage_report(
            canary_readiness,
            stage="canary",
            skip_reason="READINESS_GATE_FAILED",
            recommended_next_step="FIX_READINESS_GATE",
        )
    batches = split_custom_kg_batches(
        prepared.custom_kg_input,
        batch_size=canary_config.batch_size,
    )
    write_result = write_custom_kg_batches_to_lightrag(batches, config=canary_config)
    return _merge_write_result(
        canary_readiness,
        write_result,
        stage="canary",
        recommended_next_step=_canary_recommended_next_step(write_result, canary_readiness),
    )


def run_module_level_dsl_knowledge_ingestion(
    canary_report: DslKnowledgeIngestionReport,
    *,
    config: DslKnowledgeIngestionConfig,
    source_path: str | None = None,
    dsl_payload=None,
    module_name: str | None = None,
) -> DslKnowledgeIngestionReport:
    if not _canary_prerequisite_passed(canary_report):
        return _blocked_stage_report(
            canary_report,
            stage="module",
            skip_reason="CANARY_INGESTION_FAILED",
            recommended_next_step="RUN_CANARY_TEST_GRAPH_INGESTION",
        )
    module_config = _module_config(config)
    _payload, prepared, module_readiness = build_readiness_artifacts(
        config=module_config,
        dsl_payload=dsl_payload,
        source_path=source_path,
        module_name=module_name,
    )
    if not module_readiness.ready_to_write:
        return _blocked_stage_report(
            module_readiness,
            stage="module",
            skip_reason="READINESS_GATE_FAILED",
            recommended_next_step=_module_readiness_failure_next_step(module_readiness),
        )
    batches = split_custom_kg_batches(
        prepared.custom_kg_input,
        batch_size=module_config.batch_size,
    )
    write_result = write_custom_kg_batches_to_lightrag(batches, config=module_config)
    return _merge_write_result(
        module_readiness,
        write_result,
        stage="module",
        recommended_next_step=_module_recommended_next_step(
            write_result,
            module_readiness,
        ),
        canary_prerequisite_passed=True,
    )


def split_custom_kg_batches(
    custom_kg: dict[str, list[dict[str, Any]]],
    *,
    batch_size: int,
) -> list[dict[str, list[dict[str, Any]]]]:
    batch_size = max(1, batch_size)
    chunks = list(custom_kg.get("chunks", []))
    entities = list(custom_kg.get("entities", []))
    relationships = list(custom_kg.get("relationships", []))
    if not chunks and not entities and not relationships:
        return []
    object_count = len(entities) + len(relationships)
    if object_count <= batch_size:
        return [custom_kg]

    chunk_by_id = {str(chunk.get("source_id")): chunk for chunk in chunks}
    entity_by_name = {str(entity.get("entity_name")): entity for entity in entities}
    used_entity_names: set[str] = set()
    batches: list[dict[str, list[dict[str, Any]]]] = []

    current_relationships: list[dict[str, Any]] = []
    current_entity_names: set[str] = set()
    for relationship in relationships:
        needed = {
            str(relationship.get("src_id")),
            str(relationship.get("tgt_id")),
        }
        next_count = len(current_relationships) + 1 + len(current_entity_names | needed)
        if current_relationships and next_count > batch_size:
            batches.append(
                _build_custom_kg_batch(
                    chunk_by_id,
                    entity_by_name,
                    current_entity_names,
                    current_relationships,
                )
            )
            used_entity_names.update(current_entity_names)
            current_relationships = []
            current_entity_names = set()
        current_relationships.append(relationship)
        current_entity_names.update(needed)
    if current_relationships:
        batches.append(
            _build_custom_kg_batch(
                chunk_by_id,
                entity_by_name,
                current_entity_names,
                current_relationships,
            )
        )
        used_entity_names.update(current_entity_names)

    remaining_entities = [
        entity
        for entity in entities
        if str(entity.get("entity_name")) not in used_entity_names
    ]
    for index in range(0, len(remaining_entities), batch_size):
        batch_entities = remaining_entities[index : index + batch_size]
        source_ids = {str(entity.get("source_id")) for entity in batch_entities}
        batches.append(
            {
                "chunks": [
                    chunk_by_id[source_id]
                    for source_id in source_ids
                    if source_id in chunk_by_id
                ],
                "entities": batch_entities,
                "relationships": [],
            }
        )
    return [batch for batch in batches if batch["chunks"] or batch["entities"] or batch["relationships"]]


def _build_custom_kg_batch(
    chunk_by_id: dict[str, dict[str, Any]],
    entity_by_name: dict[str, dict[str, Any]],
    entity_names: set[str],
    relationships: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    batch_entities = [
        entity_by_name[name]
        for name in sorted(entity_names)
        if name in entity_by_name
    ]
    source_ids = {
        str(item.get("source_id"))
        for item in [*batch_entities, *relationships]
        if item.get("source_id")
    }
    return {
        "chunks": [
            chunk_by_id[source_id]
            for source_id in sorted(source_ids)
            if source_id in chunk_by_id
        ],
        "entities": batch_entities,
        "relationships": [
            relationship
            for relationship in relationships
            if relationship.get("src_id") in entity_names
            and relationship.get("tgt_id") in entity_names
        ],
    }


def _stage_config(
    config: DslKnowledgeIngestionConfig,
    stage: str,
) -> DslKnowledgeIngestionConfig:
    return replace(config, ingest_mode=stage)


def _canary_config(config: DslKnowledgeIngestionConfig) -> DslKnowledgeIngestionConfig:
    return replace(
        config,
        ingest_mode="canary",
        max_chunks=config.canary_max_chunks,
        max_entities=config.canary_max_entities,
        max_relationships=config.canary_max_relationships,
        batch_size=min(config.batch_size, 20),
        cleanup_after_run=True,
        rollback_after_run=True,
    )


def _module_config(config: DslKnowledgeIngestionConfig) -> DslKnowledgeIngestionConfig:
    return replace(
        config,
        ingest_mode="module",
        max_chunks=config.module_max_chunks,
        max_entities=config.module_max_entities,
        max_relationships=config.module_max_relationships,
    )


def _merge_write_result(
    readiness_report: DslKnowledgeIngestionReport,
    write_result: WriteResult,
    *,
    stage: str,
    recommended_next_step: str,
    canary_prerequisite_passed: bool = False,
) -> DslKnowledgeIngestionReport:
    issues = [*readiness_report.issues, *write_result.issues]
    how_to_cleanup = (
        _cleanup_hint(write_result.working_dir, cleanup_after_run=readiness_report.cleanup_after_run)
        if stage == "module"
        else None
    )
    return replace(
        readiness_report,
        stage=stage,
        skipped=write_result.skipped,
        skip_reason=write_result.skip_reason,
        working_dir=write_result.working_dir,
        batch_count=write_result.batch_count or readiness_report.batch_count,
        failed_batch_count=write_result.failed_batch_count,
        ainsert_custom_kg_called=write_result.ainsert_custom_kg_called,
        graph_write_succeeded=write_result.graph_write_succeeded,
        neo4j_connected=write_result.neo4j_connected,
        production_write=write_result.production_write,
        formal_graph_written=write_result.formal_graph_written,
        cleanup_passed=write_result.cleanup_passed,
        rollback_passed=write_result.rollback_passed,
        canary_prerequisite_passed=canary_prerequisite_passed,
        graph_storage_type=SMOKE_GRAPH_STORAGE,
        cleanup_after_run=(
            readiness_report.cleanup_after_run
            if stage != "module"
            else _module_config_value(readiness_report, "cleanup_after_run")
        ),
        rollback_after_run=(
            readiness_report.rollback_after_run
            if stage != "module"
            else _module_config_value(readiness_report, "rollback_after_run")
        ),
        how_to_cleanup=how_to_cleanup,
        issues=issues,
        recommended_next_step=recommended_next_step,
    )


def _canary_recommended_next_step(
    write_result: WriteResult,
    readiness_report: DslKnowledgeIngestionReport,
) -> str:
    if not readiness_report.sidecar_alignment_passed:
        return "FIX_SIDECAR_ALIGNMENT"
    if not write_result.graph_write_succeeded:
        return "FIX_CANARY_GRAPH_WRITE"
    if not write_result.rollback_passed:
        return "FIX_CANARY_ROLLBACK"
    if not write_result.cleanup_passed:
        return "FIX_CANARY_CLEANUP"
    return "RUN_MODULE_LEVEL_TEST_GRAPH_INGESTION"


def _module_recommended_next_step(
    write_result: WriteResult,
    readiness_report: DslKnowledgeIngestionReport,
) -> str:
    if not readiness_report.sidecar_alignment_passed:
        return "FIX_SIDECAR_ALIGNMENT"
    if not readiness_report.endpoint_closure_passed:
        return "FIX_ENDPOINT_CLOSURE"
    if not write_result.graph_write_succeeded:
        return "FIX_MODULE_GRAPH_WRITE"
    return "RUN_ACTUAL_EFFECT_TESTS_ON_TEST_GRAPH"


def _module_readiness_failure_next_step(
    readiness_report: DslKnowledgeIngestionReport,
) -> str:
    if not readiness_report.sidecar_alignment_passed:
        return "FIX_SIDECAR_ALIGNMENT"
    if not readiness_report.endpoint_closure_passed:
        return "FIX_ENDPOINT_CLOSURE"
    return "FIX_READINESS_GATE"


def _blocked_stage_report(
    report: DslKnowledgeIngestionReport,
    *,
    stage: str,
    skip_reason: str,
    recommended_next_step: str,
) -> DslKnowledgeIngestionReport:
    return replace(
        report,
        stage=stage,
        skipped=True,
        skip_reason=skip_reason,
        ready_to_write=False,
        canary_prerequisite_passed=False,
        ainsert_custom_kg_called=False,
        graph_write_succeeded=False,
        recommended_next_step=recommended_next_step,
    )


def _canary_prerequisite_passed(report: DslKnowledgeIngestionReport) -> bool:
    return (
        report.stage == "canary"
        and report.graph_write_succeeded
        and report.rollback_passed
        and report.cleanup_passed
        and not report.neo4j_connected
        and not report.production_write
        and not report.formal_graph_written
        and report.failed_batch_count == 0
    )


def _cleanup_hint(
    working_dir: str | None,
    *,
    cleanup_after_run: bool,
) -> str | None:
    if not working_dir:
        return None
    if cleanup_after_run:
        return None
    return (
        "Test graph working_dir retained for effect testing. "
        "Remove it manually when finished or rerun module ingestion with "
        f"cleanup/rollback enabled. working_dir={working_dir}"
    )


def _module_config_value(
    report: DslKnowledgeIngestionReport,
    field_name: str,
) -> bool:
    return bool(getattr(report, field_name))


__all__ = [
    "DslKnowledgeIngestionConfig",
    "DslKnowledgeIngestionReport",
    "run_canary_dsl_knowledge_ingestion",
    "run_dsl_knowledge_ingestion",
    "run_module_level_dsl_knowledge_ingestion",
    "serialize_dsl_knowledge_ingestion_report",
    "split_custom_kg_batches",
]
