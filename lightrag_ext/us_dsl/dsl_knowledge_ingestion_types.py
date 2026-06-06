from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar


ENABLE_DSL_KNOWLEDGE_INGESTION_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_KNOWLEDGE_INGESTION"
INGEST_MODE_ENV = "LIGHTRAG_DSL_INGEST_MODE"
INGEST_NAMESPACE_ENV = "LIGHTRAG_DSL_INGEST_NAMESPACE"
INGEST_SOURCE_ENV = "LIGHTRAG_DSL_INGEST_SOURCE"
INGEST_MODULE_ENV = "LIGHTRAG_DSL_INGEST_MODULE"
INGEST_CLEANUP_ENV = "LIGHTRAG_DSL_INGEST_CLEANUP"
INGEST_ROLLBACK_ENV = "LIGHTRAG_DSL_INGEST_ROLLBACK"
INGEST_WORKING_DIR_ENV = "LIGHTRAG_DSL_INGEST_WORKING_DIR"


@dataclass
class DslKnowledgeIngestionConfig:
    __test__: ClassVar[bool] = False

    enabled: bool = False
    source: str | None = None
    source_path: str | None = None
    module_name: str | None = None
    namespace: str = "dsl_test_knowledge_ingestion"
    target_graph_type: str = "test_graph"
    ingest_mode: str = "readiness"
    test_namespace_only: bool = True
    allow_production: bool = False
    allow_neo4j: bool = False
    use_temp_working_dir: bool = True
    working_dir: str | None = None
    force_local_graph_storage: bool = True
    isolate_remote_graph_env: bool = True
    use_fake_embedding: bool = True
    use_fake_llm: bool = True
    explicit_local_tokenizer: bool = True
    max_chunks: int = 2000
    max_entities: int = 5000
    max_relationships: int = 5000
    canary_max_chunks: int = 20
    canary_max_entities: int = 50
    canary_max_relationships: int = 50
    module_max_chunks: int = 2000
    module_max_entities: int = 5000
    module_max_relationships: int = 5000
    batch_size: int = 100
    timeout_seconds: int = 300
    cleanup_after_run: bool = False
    rollback_after_run: bool = False
    write_sidecar: bool = True
    feature_flag_name: str = "enable_dsl_aware_knowledge_ingestion"

    @classmethod
    def from_env(cls) -> "DslKnowledgeIngestionConfig":
        return cls(
            enabled=os.getenv(ENABLE_DSL_KNOWLEDGE_INGESTION_ENV) == "1",
            ingest_mode=os.getenv(INGEST_MODE_ENV) or "readiness",
            namespace=os.getenv(INGEST_NAMESPACE_ENV) or "dsl_test_knowledge_ingestion",
            source_path=os.getenv(INGEST_SOURCE_ENV),
            module_name=os.getenv(INGEST_MODULE_ENV),
            working_dir=os.getenv(INGEST_WORKING_DIR_ENV),
            cleanup_after_run=_env_bool(INGEST_CLEANUP_ENV, default=False),
            rollback_after_run=_env_bool(INGEST_ROLLBACK_ENV, default=False),
        )


@dataclass
class DslKnowledgeIngestionReport:
    __test__: ClassVar[bool] = False

    enabled: bool
    skipped: bool
    skip_reason: str | None
    stage: str
    ready_to_write: bool
    canary_prerequisite_passed: bool
    module_name: str | None
    source: str | None
    namespace: str
    working_dir: str | None
    source_us_count: int
    source_text_unit_count: int
    domain_distribution: dict[str, int]
    version_policy_ready: bool
    version_review_required_before: int
    version_review_required_after: int
    unsafe_supersedes_blocked_count: int
    source_order_supersedes_count: int
    kg_payload_chunk_count: int
    kg_payload_entity_count: int
    kg_payload_relationship_count: int
    approved_chunk_count: int
    approved_entity_count: int
    approved_relationship_count: int
    blocked_object_count: int
    blocked_reason_occurrence_count: int
    blocked_count: int
    block_reason_distribution: dict[str, int]
    custom_kg_chunk_count: int
    custom_kg_entity_count: int
    custom_kg_relationship_count: int
    dropped_relationship_due_to_endpoint_count: int
    truncated_entity_count: int
    truncated_relationship_count: int
    sidecar_record_count: int
    sidecar_alignment_passed: bool
    endpoint_closure_passed: bool
    dangling_relationship_count: int
    forbidden_relation_count: int
    idempotency_key_duplicate_count: int
    batch_count: int
    failed_batch_count: int
    ainsert_custom_kg_called: bool
    graph_write_succeeded: bool
    neo4j_connected: bool
    production_write: bool
    formal_graph_written: bool
    cleanup_passed: bool
    rollback_passed: bool
    graph_storage_type: str
    cleanup_after_run: bool
    rollback_after_run: bool
    rollback_plan_present: bool
    rollback_key_count: int
    rollback_strategy: str | None
    idempotency_passed: bool
    evidence_missing_count: int
    version_review_required_blocked_count: int
    review_required_blocked_count: int
    info_only_blocked_count: int
    invalid_relation_blocked_count: int
    forbidden_relation_blocked_count: int
    dangling_relationship_blocked_count: int
    issues: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    how_to_cleanup: str | None = None
    recommended_next_step: str = ""


def serialize_dsl_knowledge_ingestion_report(
    report: DslKnowledgeIngestionReport,
) -> dict[str, Any]:
    return asdict(report)


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y"}


__all__ = [
    "DslKnowledgeIngestionConfig",
    "DslKnowledgeIngestionReport",
    "serialize_dsl_knowledge_ingestion_report",
]
