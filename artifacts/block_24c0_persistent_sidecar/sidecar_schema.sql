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
