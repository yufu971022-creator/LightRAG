from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from .kg_metadata_sidecar import (
    KgMetadataSidecarRecord,
    KgMetadataSidecarStore,
    build_graph_insert_sidecar_records,
    build_metadata_sidecar_records,
    serialize_graph_insert_sidecar_alignment_report,
    serialize_sidecar_coverage_report,
    validate_graph_insert_sidecar_alignment,
    validate_sidecar_coverage,
)
from .kg_payload_types import DslKgPayload
from .kg_schema_policy import FORBIDDEN_RELATION_TYPES


ENABLE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_TEST_GRAPH_WRITE"
NAMESPACE_ENV = "LIGHTRAG_DSL_TEST_GRAPH_NAMESPACE"
KEEP_DATA_ENV = "LIGHTRAG_DSL_TEST_GRAPH_KEEP_DATA"


@dataclass(frozen=True)
class TestGraphWriteConfig:
    __test__: ClassVar[bool] = False

    enabled: bool = False
    dry_run: bool = True
    test_namespace_only: bool = True
    namespace: str = "dsl_test_graph"
    working_dir: str | None = None
    use_temp_working_dir: bool = True
    write_graph: bool = False
    write_formal_graph: bool = False
    write_confirmed: bool = False
    include_review_required: bool = False
    include_info_only: bool = False
    use_sidecar: bool = True
    cleanup_after_run: bool = True
    rollback_after_run: bool = True
    max_entities: int = 50
    max_relationships: int = 50
    hard_max_entities: int = 100
    hard_max_relationships: int = 100
    feature_flag_name: str = "enable_dsl_aware_test_graph_write"

    @classmethod
    def from_env(cls) -> "TestGraphWriteConfig":
        keep_data = os.getenv(KEEP_DATA_ENV) == "1"
        enabled = os.getenv(ENABLE_ENV) == "1"
        return cls(
            enabled=enabled,
            write_graph=enabled,
            namespace=os.getenv(NAMESPACE_ENV) or "dsl_test_graph",
            cleanup_after_run=not keep_data,
            rollback_after_run=not keep_data,
        )


@dataclass
class TestGraphWriteReport:
    __test__: ClassVar[bool] = False

    enabled: bool
    skipped: bool
    skip_reason: str | None
    namespace: str
    working_dir: str | None
    custom_kg_chunk_count: int
    custom_kg_entity_count: int
    custom_kg_relationship_count: int
    ainsert_custom_kg_called: bool
    graph_write_called: bool
    neo4j_write_called: bool
    formal_graph_written: bool
    confirmed_written: bool
    review_required_written: bool
    info_only_written: bool
    sidecar_record_count: int
    full_sidecar_record_count: int
    graph_insert_sidecar_record_count: int
    graph_insert_sidecar_alignment_status: str | None
    sidecar_coverage_passed: bool
    cleanup_passed: bool
    rollback_supported: bool
    production_namespace_blocked: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommended_next_step: str = ""
    risks: list[str] = field(default_factory=list)


def to_lightrag_custom_kg_input(
    payload: DslKgPayload,
    *,
    max_entities: int | None = None,
    max_relationships: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    entities = payload.entities[:max_entities] if max_entities is not None else payload.entities
    relationships = (
        payload.relationships[:max_relationships]
        if max_relationships is not None
        else payload.relationships
    )
    return {
        "chunks": [
            {
                "content": chunk.content,
                "source_id": chunk.source_id,
            }
            for chunk in payload.chunks
        ],
        "entities": [
            {
                "entity_name": entity.entity_name,
                "entity_type": entity.entity_type,
                "description": entity.description,
                "source_id": entity.source_id,
            }
            for entity in entities
        ],
        "relationships": [
            {
                "src_id": relationship.src_id,
                "tgt_id": relationship.tgt_id,
                "description": relationship.description,
                "keywords": relationship.keywords,
                "source_id": relationship.source_id,
                "weight": relationship.weight,
            }
            for relationship in relationships
        ],
    }


def run_test_graph_write_dry_run(
    payload: DslKgPayload,
    *,
    lightrag_client=None,
    sidecar_store: KgMetadataSidecarStore | None = None,
    config: TestGraphWriteConfig | None = None,
    sidecar_records: list[KgMetadataSidecarRecord] | None = None,
) -> TestGraphWriteReport:
    return asyncio.run(
        arun_test_graph_write_dry_run(
            payload,
            lightrag_client=lightrag_client,
            sidecar_store=sidecar_store,
            config=config,
            sidecar_records=sidecar_records,
        )
    )


async def arun_test_graph_write_dry_run(
    payload: DslKgPayload,
    *,
    lightrag_client=None,
    sidecar_store: KgMetadataSidecarStore | None = None,
    config: TestGraphWriteConfig | None = None,
    sidecar_records: list[KgMetadataSidecarRecord] | None = None,
) -> TestGraphWriteReport:
    config = config or TestGraphWriteConfig()
    sidecar_store = sidecar_store or KgMetadataSidecarStore()
    risks: list[str] = []

    if not config.enabled:
        return _report(
            config,
            skipped=True,
            skip_reason="Feature flag enable_dsl_aware_test_graph_write is disabled.",
            recommended_next_step="ENABLE_FEATURE_FLAG_TO_TEST_GRAPH_WRITE",
        )
    if not config.write_graph:
        return _report(
            config,
            skipped=True,
            skip_reason="write_graph is disabled.",
            recommended_next_step="ENABLE_FEATURE_FLAG_TO_TEST_GRAPH_WRITE",
        )
    if config.write_formal_graph:
        return _blocked_report(
            config,
            "FORMAL_GRAPH_WRITE_FORBIDDEN",
            "formal graph write is forbidden in Block 18.",
            recommended_next_step="DO_NOT_WRITE_GRAPH",
        )
    if config.test_namespace_only and not _is_safe_test_namespace(config.namespace):
        return _blocked_report(
            config,
            "PRODUCTION_NAMESPACE_BLOCKED",
            "namespace must contain test or dsl_test.",
            production_namespace_blocked=True,
            recommended_next_step="DO_NOT_WRITE_GRAPH",
        )
    if config.working_dir and not _is_safe_working_dir(config.working_dir):
        return _blocked_report(
            config,
            "UNSAFE_WORKING_DIR_BLOCKED",
            "working_dir must be temporary or explicitly test-scoped.",
            production_namespace_blocked=True,
            recommended_next_step="DO_NOT_WRITE_GRAPH",
        )

    guard_issues = _payload_guard_issues(payload, config)
    if guard_issues:
        return _report(
            config,
            skipped=True,
            skip_reason=guard_issues[0]["code"],
            issues=guard_issues,
            recommended_next_step="DO_NOT_WRITE_GRAPH",
        )

    full_sidecar_records = sidecar_records or build_metadata_sidecar_records(
        payload,
        namespace=config.namespace,
    )
    coverage = validate_sidecar_coverage(payload, full_sidecar_records)
    if coverage.pass_status != "PASS":
        return _report(
            config,
            skipped=True,
            skip_reason="SIDECAR_COVERAGE_FAIL",
            sidecar_record_count=len(full_sidecar_records),
            full_sidecar_record_count=len(full_sidecar_records),
            sidecar_coverage_passed=False,
            issues=[
                {
                    "severity": "ERROR",
                    "code": "SIDECAR_COVERAGE_FAIL",
                    "message": "Sidecar coverage failed; graph write blocked.",
                    "coverage": serialize_sidecar_coverage_report(coverage),
                }
            ],
            recommended_next_step="FIX_METADATA_SIDECAR",
        )

    entity_limit = min(config.max_entities, config.hard_max_entities)
    relationship_limit = min(config.max_relationships, config.hard_max_relationships)
    if len(payload.entities) > entity_limit:
        risks.append(f"Entity payload truncated from {len(payload.entities)} to {entity_limit}.")
    if len(payload.relationships) > relationship_limit:
        risks.append(
            f"Relationship payload truncated from {len(payload.relationships)} to {relationship_limit}."
        )
    custom_kg = to_lightrag_custom_kg_input(
        payload,
        max_entities=entity_limit,
        max_relationships=relationship_limit,
    )
    source_issues = _source_id_guard_issues(custom_kg)
    if source_issues:
        return _report(
            config,
            skipped=True,
            skip_reason=source_issues[0]["code"],
            custom_kg=custom_kg,
            sidecar_record_count=len(full_sidecar_records),
            full_sidecar_record_count=len(full_sidecar_records),
            sidecar_coverage_passed=True,
            issues=source_issues,
            recommended_next_step="DO_NOT_WRITE_GRAPH",
            risks=risks,
        )

    graph_insert_sidecar_records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace=config.namespace,
    )
    alignment = validate_graph_insert_sidecar_alignment(
        custom_kg,
        graph_insert_sidecar_records,
    )
    if alignment.pass_status != "PASS":
        return _report(
            config,
            skipped=True,
            skip_reason="GRAPH_INSERT_SIDECAR_ALIGNMENT_FAIL",
            custom_kg=custom_kg,
            sidecar_record_count=len(graph_insert_sidecar_records),
            full_sidecar_record_count=len(full_sidecar_records),
            graph_insert_sidecar_record_count=len(graph_insert_sidecar_records),
            graph_insert_sidecar_alignment_status=alignment.pass_status,
            sidecar_coverage_passed=True,
            issues=[
                {
                    "severity": "ERROR",
                    "code": "GRAPH_INSERT_SIDECAR_ALIGNMENT_FAIL",
                    "message": "Graph insert sidecar does not match custom_kg input.",
                    "alignment": serialize_graph_insert_sidecar_alignment_report(
                        alignment
                    ),
                }
            ],
            recommended_next_step="FIX_METADATA_SIDECAR",
            risks=risks,
        )

    sidecar_store.upsert_records(graph_insert_sidecar_records)
    if lightrag_client is None:
        return _report(
            config,
            skipped=True,
            skip_reason="LIGHTRAG_CLIENT_NOT_PROVIDED",
            custom_kg=custom_kg,
            sidecar_record_count=len(graph_insert_sidecar_records),
            full_sidecar_record_count=len(full_sidecar_records),
            graph_insert_sidecar_record_count=len(graph_insert_sidecar_records),
            graph_insert_sidecar_alignment_status=alignment.pass_status,
            sidecar_coverage_passed=True,
            recommended_next_step="ENABLE_FEATURE_FLAG_TO_TEST_GRAPH_WRITE",
            risks=risks,
        )

    await lightrag_client.ainsert_custom_kg(custom_kg, full_doc_id=config.namespace)
    cleanup_passed = True
    if config.cleanup_after_run or config.rollback_after_run:
        cleanup_passed = _cleanup(config, sidecar_store)

    return _report(
        config,
        skipped=False,
        skip_reason=None,
        custom_kg=custom_kg,
        ainsert_custom_kg_called=True,
        graph_write_called=True,
        neo4j_write_called=bool(getattr(lightrag_client, "neo4j_write_called", False)),
        sidecar_record_count=len(graph_insert_sidecar_records),
        full_sidecar_record_count=len(full_sidecar_records),
        graph_insert_sidecar_record_count=len(graph_insert_sidecar_records),
        graph_insert_sidecar_alignment_status=alignment.pass_status,
        sidecar_coverage_passed=True,
        cleanup_passed=cleanup_passed,
        rollback_supported=True,
        recommended_next_step=(
            "EVALUATE_GRAPH_RETRIEVAL_ON_TEST_NAMESPACE"
            if cleanup_passed
            else "FIX_GRAPH_ROLLBACK_BEFORE_NEXT_STEP"
        ),
        risks=risks,
    )


def serialize_test_graph_write_report(report: TestGraphWriteReport) -> dict[str, Any]:
    return asdict(report)


def _payload_guard_issues(
    payload: DslKgPayload,
    config: TestGraphWriteConfig,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    statuses = [
        str(item.metadata.get("knowledgeStatus") or "")
        for item in [*payload.entities, *payload.relationships]
    ]
    if any(status == "Confirmed" for status in statuses) and not config.write_confirmed:
        issues.append(_issue("CONFIRMED_PAYLOAD_BLOCKED", "Confirmed payload is forbidden."))
    if any(status == "ReviewRequired" for status in statuses) and not config.include_review_required:
        issues.append(_issue("REVIEW_REQUIRED_PAYLOAD_BLOCKED", "ReviewRequired payload is forbidden."))
    if any(status == "InfoOnly" for status in statuses) and not config.include_info_only:
        issues.append(_issue("INFO_ONLY_PAYLOAD_BLOCKED", "InfoOnly payload is forbidden."))
    forbidden = [
        relationship.keywords
        for relationship in payload.relationships
        if relationship.keywords in FORBIDDEN_RELATION_TYPES
    ]
    if forbidden:
        issues.append(
            _issue(
                "FORBIDDEN_RELATION_BLOCKED",
                f"Forbidden relation found: {', '.join(sorted(set(forbidden)))}.",
            )
        )
    return issues


def _source_id_guard_issues(custom_kg: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    chunk_source_ids = {item["source_id"] for item in custom_kg.get("chunks", [])}
    issues: list[dict[str, Any]] = []
    for item in custom_kg.get("entities", []):
        if item.get("source_id") not in chunk_source_ids:
            issues.append(
                _issue(
                    "ENTITY_SOURCE_ID_MISSING_CHUNK",
                    f"Entity source_id {item.get('source_id')} has no matching chunk.",
                )
            )
    for item in custom_kg.get("relationships", []):
        if item.get("source_id") not in chunk_source_ids:
            issues.append(
                _issue(
                    "RELATIONSHIP_SOURCE_ID_MISSING_CHUNK",
                    f"Relationship source_id {item.get('source_id')} has no matching chunk.",
                )
            )
    return issues


def _is_safe_test_namespace(namespace: str) -> bool:
    lowered = namespace.lower()
    return (
        ("test" in lowered or "dsl_test" in lowered)
        and lowered not in {"default", "main", "prod", "production"}
    )


def _is_safe_working_dir(working_dir: str) -> bool:
    lowered = str(Path(working_dir)).lower()
    return "/tmp" in lowered or "/private/tmp" in lowered or "test" in lowered


def _cleanup(config: TestGraphWriteConfig, sidecar_store: KgMetadataSidecarStore) -> bool:
    sidecar_store.delete_by_namespace(config.namespace)
    if not config.working_dir:
        return True
    path = Path(config.working_dir)
    if path.exists() and _is_safe_working_dir(str(path)):
        shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def _blocked_report(
    config: TestGraphWriteConfig,
    code: str,
    message: str,
    *,
    production_namespace_blocked: bool = False,
    recommended_next_step: str,
) -> TestGraphWriteReport:
    return _report(
        config,
        skipped=True,
        skip_reason=code,
        production_namespace_blocked=production_namespace_blocked,
        issues=[_issue(code, message)],
        recommended_next_step=recommended_next_step,
    )


def _report(
    config: TestGraphWriteConfig,
    *,
    skipped: bool,
    skip_reason: str | None,
    custom_kg: dict[str, list[dict[str, Any]]] | None = None,
    ainsert_custom_kg_called: bool = False,
    graph_write_called: bool = False,
    neo4j_write_called: bool = False,
    sidecar_record_count: int = 0,
    full_sidecar_record_count: int = 0,
    graph_insert_sidecar_record_count: int = 0,
    graph_insert_sidecar_alignment_status: str | None = None,
    sidecar_coverage_passed: bool = False,
    cleanup_passed: bool = False,
    rollback_supported: bool = False,
    production_namespace_blocked: bool = False,
    issues: list[dict[str, Any]] | None = None,
    recommended_next_step: str = "",
    risks: list[str] | None = None,
) -> TestGraphWriteReport:
    custom_kg = custom_kg or {"chunks": [], "entities": [], "relationships": []}
    return TestGraphWriteReport(
        enabled=config.enabled,
        skipped=skipped,
        skip_reason=skip_reason,
        namespace=config.namespace,
        working_dir=config.working_dir,
        custom_kg_chunk_count=len(custom_kg.get("chunks", [])),
        custom_kg_entity_count=len(custom_kg.get("entities", [])),
        custom_kg_relationship_count=len(custom_kg.get("relationships", [])),
        ainsert_custom_kg_called=ainsert_custom_kg_called,
        graph_write_called=graph_write_called,
        neo4j_write_called=neo4j_write_called,
        formal_graph_written=False,
        confirmed_written=False,
        review_required_written=False,
        info_only_written=False,
        sidecar_record_count=sidecar_record_count,
        full_sidecar_record_count=full_sidecar_record_count,
        graph_insert_sidecar_record_count=graph_insert_sidecar_record_count,
        graph_insert_sidecar_alignment_status=graph_insert_sidecar_alignment_status,
        sidecar_coverage_passed=sidecar_coverage_passed,
        cleanup_passed=cleanup_passed,
        rollback_supported=rollback_supported,
        production_namespace_blocked=production_namespace_blocked,
        issues=issues or [],
        recommended_next_step=recommended_next_step,
        risks=risks or [],
    )


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": message}


__all__ = [
    "TestGraphWriteConfig",
    "TestGraphWriteReport",
    "arun_test_graph_write_dry_run",
    "run_test_graph_write_dry_run",
    "serialize_test_graph_write_report",
    "to_lightrag_custom_kg_input",
]
