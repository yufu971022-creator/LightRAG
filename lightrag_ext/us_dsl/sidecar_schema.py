from __future__ import annotations

from pathlib import Path

REQUIRED_TABLES = [
    "documents",
    "document_versions",
    "ingestion_batches",
    "batch_documents",
    "raw_evidence_chunks",
    "source_text_units",
    "chunk_text_unit_links",
    "semantic_objects",
    "semantic_relations",
    "graph_object_mappings",
    "evidence_mappings",
    "term_mappings",
    "version_groups",
    "version_members",
    "ingestion_issues",
    "rollback_records",
]

LIFECYCLE_SCHEMA_VERSION = 2
LIFECYCLE_MIGRATION_ID = "002_document_lifecycle"

LIFECYCLE_REQUIRED_TABLES = [
    "schema_migrations",
    "document_active_versions",
    "document_version_state_history",
    "raw_chunk_contributions",
    "semantic_object_contributions",
    "semantic_relation_contributions",
    "lifecycle_mutations",
    "lifecycle_mutation_steps",
    "document_tombstones",
    "rebuild_requests",
]

ALL_TABLES = [*REQUIRED_TABLES, *LIFECYCLE_REQUIRED_TABLES]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source_uri_hash TEXT NOT NULL UNIQUE,
    source_type TEXT,
    module_code TEXT,
    logical_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
    document_version_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
    content_hash TEXT NOT NULL,
    parser_name TEXT,
    parser_version TEXT,
    normalized_text_hash TEXT,
    status TEXT,
    previous_version_id TEXT REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    UNIQUE(document_id, content_hash)
);

CREATE TABLE IF NOT EXISTS ingestion_batches (
    batch_id TEXT PRIMARY KEY,
    trace_id TEXT UNIQUE NOT NULL,
    requested_mode TEXT,
    semantic_route TEXT,
    status TEXT NOT NULL CHECK(status IN ('STARTED', 'COMPLETED', 'FAILED')),
    policy_version TEXT,
    ontology_version TEXT,
    term_registry_version TEXT,
    pfss_namespace TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    error_summary TEXT,
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS batch_documents (
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    PRIMARY KEY(batch_id, document_version_id)
);

CREATE TABLE IF NOT EXISTS raw_evidence_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    chunk_order INTEGER NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    token_count INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    source_span_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(document_version_id, chunk_order),
    UNIQUE(document_version_id, content_hash, start_offset, end_offset)
);

CREATE TABLE IF NOT EXISTS source_text_units (
    text_unit_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    source_us_id TEXT,
    section_type TEXT,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    text_hash TEXT NOT NULL,
    feature_key TEXT,
    primary_domain TEXT,
    related_domains_json TEXT NOT NULL,
    evidence_excerpt TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk_text_unit_links (
    link_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    chunk_id TEXT NOT NULL REFERENCES raw_evidence_chunks(chunk_id) ON DELETE RESTRICT,
    text_unit_id TEXT NOT NULL REFERENCES source_text_units(text_unit_id) ON DELETE RESTRICT,
    overlap_start_offset INTEGER NOT NULL,
    overlap_end_offset INTEGER NOT NULL,
    overlap_char_count INTEGER NOT NULL,
    chunk_coverage_ratio REAL NOT NULL,
    text_unit_coverage_ratio REAL NOT NULL,
    link_type TEXT NOT NULL,
    UNIQUE(chunk_id, text_unit_id, overlap_start_offset, overlap_end_offset)
);

CREATE TABLE IF NOT EXISTS semantic_objects (
    semantic_object_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    object_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    domain_code TEXT,
    feature_key TEXT,
    knowledge_status TEXT,
    validation_status TEXT,
    review_decision TEXT,
    version_group_key TEXT,
    idempotency_key TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semantic_relations (
    semantic_relation_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    src_semantic_object_id TEXT NOT NULL REFERENCES semantic_objects(semantic_object_id) ON DELETE RESTRICT,
    relation_type TEXT NOT NULL,
    tgt_semantic_object_id TEXT NOT NULL REFERENCES semantic_objects(semantic_object_id) ON DELETE RESTRICT,
    knowledge_status TEXT,
    validation_status TEXT,
    review_decision TEXT,
    idempotency_key TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_object_mappings (
    mapping_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    graph_space TEXT NOT NULL,
    graph_namespace TEXT NOT NULL,
    graph_object_kind TEXT NOT NULL,
    graph_object_id TEXT NOT NULL,
    semantic_object_id TEXT REFERENCES semantic_objects(semantic_object_id) ON DELETE RESTRICT,
    semantic_relation_id TEXT REFERENCES semantic_relations(semantic_relation_id) ON DELETE RESTRICT,
    source_id TEXT,
    rollback_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK ((semantic_object_id IS NOT NULL AND semantic_relation_id IS NULL) OR (semantic_object_id IS NULL AND semantic_relation_id IS NOT NULL)),
    UNIQUE(graph_space, graph_namespace, graph_object_kind, graph_object_id)
);

CREATE TABLE IF NOT EXISTS evidence_mappings (
    evidence_mapping_id TEXT PRIMARY KEY,
    semantic_object_id TEXT REFERENCES semantic_objects(semantic_object_id) ON DELETE RESTRICT,
    semantic_relation_id TEXT REFERENCES semantic_relations(semantic_relation_id) ON DELETE RESTRICT,
    text_unit_id TEXT NOT NULL REFERENCES source_text_units(text_unit_id) ON DELETE RESTRICT,
    source_span_json TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    evidence_excerpt TEXT,
    evidence_role TEXT,
    created_at TEXT NOT NULL,
    CHECK ((semantic_object_id IS NOT NULL AND semantic_relation_id IS NULL) OR (semantic_object_id IS NULL AND semantic_relation_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS term_mappings (
    term_mapping_id TEXT PRIMARY KEY,
    original_term TEXT NOT NULL,
    canonical_term TEXT NOT NULL,
    language_code TEXT,
    domain_code TEXT,
    feature_key TEXT,
    object_type TEXT,
    confidence REAL,
    mapping_status TEXT NOT NULL CHECK(mapping_status IN ('CONFIRMED', 'CANDIDATE', 'REJECTED')),
    mapping_source TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS version_groups (
    version_group_key TEXT PRIMARY KEY,
    module_code TEXT,
    domain_code TEXT,
    feature_key TEXT,
    object_type TEXT,
    object_key TEXT,
    rule_dimension TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS version_members (
    version_member_id TEXT PRIMARY KEY,
    version_group_key TEXT NOT NULL REFERENCES version_groups(version_group_key) ON DELETE RESTRICT,
    semantic_object_id TEXT NOT NULL REFERENCES semantic_objects(semantic_object_id) ON DELETE RESTRICT,
    rule_version TEXT,
    version_status TEXT,
    latest_flag INTEGER NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    supersedes_member_id TEXT REFERENCES version_members(version_member_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ingestion_issues (
    issue_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    semantic_object_id TEXT REFERENCES semantic_objects(semantic_object_id) ON DELETE RESTRICT,
    semantic_relation_id TEXT REFERENCES semantic_relations(semantic_relation_id) ON DELETE RESTRICT,
    text_unit_id TEXT REFERENCES source_text_units(text_unit_id) ON DELETE RESTRICT,
    issue_type TEXT NOT NULL,
    severity TEXT,
    reason_code TEXT,
    review_required INTEGER NOT NULL,
    issue_status TEXT NOT NULL CHECK(issue_status IN ('OPEN', 'RESOLVED', 'IGNORED')),
    evidence_excerpt TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rollback_records (
    rollback_record_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    graph_space TEXT NOT NULL,
    graph_namespace TEXT NOT NULL,
    graph_object_kind TEXT NOT NULL,
    graph_object_id TEXT NOT NULL,
    rollback_key TEXT NOT NULL,
    planned_action TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

MIGRATION_002_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_active_versions (
    document_id TEXT PRIMARY KEY REFERENCES documents(document_id) ON DELETE RESTRICT,
    active_document_version_id TEXT REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    updated_by_batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_version_state_history (
    state_history_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    old_status TEXT,
    new_status TEXT NOT NULL CHECK(new_status IN ('STAGED', 'ACTIVE', 'SUPERSEDED', 'DELETED', 'REBUILD_REQUIRED', 'REBUILDING', 'FAILED')),
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    reason_code TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_chunk_contributions (
    contribution_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    chunk_id TEXT NOT NULL,
    active_flag INTEGER NOT NULL CHECK(active_flag IN (0, 1)),
    projection_hash TEXT NOT NULL,
    created_by_batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    deactivated_by_batch_id TEXT REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_version_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS semantic_object_contributions (
    contribution_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    semantic_object_id TEXT NOT NULL REFERENCES semantic_objects(semantic_object_id) ON DELETE RESTRICT,
    active_flag INTEGER NOT NULL CHECK(active_flag IN (0, 1)),
    projection_hash TEXT NOT NULL,
    created_by_batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    deactivated_by_batch_id TEXT REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_version_id, semantic_object_id)
);

CREATE TABLE IF NOT EXISTS semantic_relation_contributions (
    contribution_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    semantic_relation_id TEXT NOT NULL REFERENCES semantic_relations(semantic_relation_id) ON DELETE RESTRICT,
    active_flag INTEGER NOT NULL CHECK(active_flag IN (0, 1)),
    projection_hash TEXT NOT NULL,
    created_by_batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    deactivated_by_batch_id TEXT REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(document_version_id, semantic_relation_id)
);

CREATE TABLE IF NOT EXISTS lifecycle_mutations (
    mutation_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
    old_document_version_id TEXT REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    new_document_version_id TEXT REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    operation_type TEXT NOT NULL CHECK(operation_type IN ('UPSERT_NEW_VERSION', 'DELETE_DOCUMENT_VERSION', 'DELETE_LOGICAL_DOCUMENT', 'REBUILD_DOCUMENT_VERSION')),
    status TEXT NOT NULL CHECK(status IN ('PLANNED', 'APPLYING', 'APPLIED', 'COMPENSATING', 'COMPENSATED', 'FAILED')),
    plan_hash TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS lifecycle_mutation_steps (
    mutation_step_id TEXT PRIMARY KEY,
    mutation_id TEXT NOT NULL REFERENCES lifecycle_mutations(mutation_id) ON DELETE RESTRICT,
    step_order INTEGER NOT NULL,
    store_kind TEXT NOT NULL,
    operation_kind TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_id TEXT NOT NULL,
    preimage_json TEXT,
    postimage_json TEXT,
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'APPLIED', 'SKIPPED', 'COMPENSATED', 'FAILED')),
    error_summary TEXT,
    executed_at TEXT,
    compensated_at TEXT,
    UNIQUE(mutation_id, step_order)
);

CREATE TABLE IF NOT EXISTS document_tombstones (
    tombstone_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE RESTRICT,
    document_version_id TEXT REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    delete_scope TEXT NOT NULL CHECK(delete_scope IN ('DOCUMENT_VERSION', 'LOGICAL_DOCUMENT')),
    reason_code TEXT NOT NULL,
    deleted_by_batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    deleted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rebuild_requests (
    rebuild_request_id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    reason_code TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('REQUESTED', 'REBUILDING', 'COMPLETED', 'FAILED')),
    requested_by_batch_id TEXT NOT NULL REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    completed_by_batch_id TEXT REFERENCES ingestion_batches(batch_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""


def write_schema_artifact(output_dir: str | Path) -> Path:
    path = Path(output_dir) / "sidecar_schema.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SCHEMA_SQL.strip() + "\n", encoding="utf-8")
    return path


def write_lifecycle_migration_artifact(output_dir: str | Path) -> Path:
    path = Path(output_dir) / "schema_migration_002.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MIGRATION_002_SQL.strip() + "\n", encoding="utf-8")
    return path
