from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class IngestionBatchRecord:
    batch_id: str
    trace_id: str
    requested_mode: str
    semantic_route: str
    status: str = "STARTED"
    policy_version: str = "24C-0-policy"
    ontology_version: str = "24C-0-ontology"
    term_registry_version: str = "24C-0-terms"
    pfss_namespace: str = "pfss_test_graph"
    started_at: str = ""
    completed_at: str | None = None
    error_code: str | None = None
    error_summary: str | None = None


@dataclass(frozen=True)
class SidecarPersistenceBundle:
    batch: IngestionBatchRecord
    document: dict[str, Any]
    document_version: dict[str, Any]
    raw_chunks: list[dict[str, Any]] = field(default_factory=list)
    source_text_units: list[dict[str, Any]] = field(default_factory=list)
    chunk_text_unit_links: list[dict[str, Any]] = field(default_factory=list)
    semantic_objects: list[dict[str, Any]] = field(default_factory=list)
    semantic_relations: list[dict[str, Any]] = field(default_factory=list)
    graph_object_mappings: list[dict[str, Any]] = field(default_factory=list)
    evidence_mappings: list[dict[str, Any]] = field(default_factory=list)
    term_mappings: list[dict[str, Any]] = field(default_factory=list)
    version_groups: list[dict[str, Any]] = field(default_factory=list)
    version_members: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    rollback_records: list[dict[str, Any]] = field(default_factory=list)
    fail_after_semantic_relations: bool = False


@dataclass(frozen=True)
class SidecarPersistenceConfig:
    artifact_root: str = "artifacts/block_24c0_persistent_sidecar"
    cleanup_after_run: bool = False


@dataclass(frozen=True)
class SidecarPersistenceResult:
    batch_id: str
    trace_id: str
    document_id: str
    document_version_id: str
    semantic_route: str
    status: str
    record_counts: dict[str, int]
    referential_integrity: dict[str, Any]
    error: dict[str, Any] | None = None


TABLE_COUNT_KEYS = {
    "documents": "documents_count",
    "document_versions": "document_versions_count",
    "ingestion_batches": "ingestion_batches_count",
    "raw_evidence_chunks": "raw_chunks_count",
    "source_text_units": "source_text_units_count",
    "chunk_text_unit_links": "chunk_text_unit_links_count",
    "semantic_objects": "semantic_objects_count",
    "semantic_relations": "semantic_relations_count",
    "graph_object_mappings": "graph_object_mappings_count",
    "evidence_mappings": "evidence_mappings_count",
    "term_mappings": "term_mappings_count",
    "version_groups": "version_groups_count",
    "version_members": "version_members_count",
    "ingestion_issues": "ingestion_issues_count",
    "rollback_records": "rollback_records_count",
}


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
