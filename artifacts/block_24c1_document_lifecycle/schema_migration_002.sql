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
