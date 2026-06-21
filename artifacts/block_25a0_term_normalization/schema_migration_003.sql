ALTER TABLE term_mappings ADD COLUMN source_language TEXT;
ALTER TABLE term_mappings ADD COLUMN canonical_language TEXT;
ALTER TABLE term_mappings ADD COLUMN synonym_type TEXT;
ALTER TABLE term_mappings ADD COLUMN system_name TEXT;
ALTER TABLE term_mappings ADD COLUMN module_code TEXT;
ALTER TABLE term_mappings ADD COLUMN requires_scope INTEGER DEFAULT 0;
ALTER TABLE term_mappings ADD COLUMN registry_version TEXT;
ALTER TABLE term_mappings ADD COLUMN effective_from TEXT;
ALTER TABLE term_mappings ADD COLUMN effective_to TEXT;
ALTER TABLE term_mappings ADD COLUMN owner TEXT;
ALTER TABLE term_mappings ADD COLUMN comments TEXT;
CREATE TABLE IF NOT EXISTS canonical_terms (
    canonical_term_id TEXT PRIMARY KEY,
    canonical_term TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    language_code TEXT,
    object_type TEXT,
    domain_code TEXT,
    feature_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_terms_scope
ON canonical_terms (
    canonical_key,
    IFNULL(object_type, ''),
    IFNULL(domain_code, ''),
    IFNULL(feature_key, '')
);

CREATE TABLE IF NOT EXISTS semantic_identity_aliases (
    alias_id TEXT PRIMARY KEY,
    semantic_object_id TEXT NOT NULL,
    term_mapping_id TEXT NOT NULL,
    original_term TEXT NOT NULL,
    lexical_key TEXT NOT NULL,
    active_flag INTEGER NOT NULL CHECK(active_flag IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE(semantic_object_id, term_mapping_id, lexical_key)
);
