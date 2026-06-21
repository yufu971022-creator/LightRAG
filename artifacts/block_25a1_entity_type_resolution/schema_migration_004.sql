ALTER TABLE semantic_objects ADD COLUMN original_entity_type TEXT;
ALTER TABLE semantic_objects ADD COLUMN resolved_entity_type TEXT;
ALTER TABLE semantic_objects ADD COLUMN type_resolution_decision TEXT;
ALTER TABLE semantic_objects ADD COLUMN type_confidence REAL;
ALTER TABLE semantic_objects ADD COLUMN type_requires_review INTEGER;
ALTER TABLE semantic_objects ADD COLUMN type_resolution_version TEXT;

CREATE TABLE IF NOT EXISTS entity_type_resolution_events (
    resolution_event_id TEXT PRIMARY KEY,
    semantic_object_id TEXT,
    document_version_id TEXT NOT NULL,
    text_unit_id TEXT,
    original_entity_name TEXT NOT NULL,
    original_entity_type TEXT,
    resolved_entity_type TEXT,
    decision TEXT NOT NULL,
    confidence REAL NOT NULL,
    candidate_types_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    requires_review INTEGER NOT NULL,
    old_semantic_object_id TEXT,
    new_semantic_object_id TEXT,
    created_at TEXT NOT NULL
);
