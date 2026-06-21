from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .term_lexical_normalizer import canonical_key, lexical_key
from .term_normalization_types import TermMappingRecord, TermScope, to_plain_dict

TERM_SCHEMA_VERSION = 3
TERM_MIGRATION_ID = "003_term_normalization_v2"

TERM_MIGRATION_003_SQL = """
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
"""

TERM_MAPPING_EXTRA_COLUMNS = {
    "source_language": "TEXT",
    "canonical_language": "TEXT",
    "synonym_type": "TEXT",
    "system_name": "TEXT",
    "module_code": "TEXT",
    "requires_scope": "INTEGER DEFAULT 0",
    "registry_version": "TEXT",
    "effective_from": "TEXT",
    "effective_to": "TEXT",
    "owner": "TEXT",
    "comments": "TEXT",
}


class TermRegistryConflictError(ValueError):
    pass


class TermRegistry:
    def __init__(self, *, registry_version: str = "25A-0", allow_conflicts: bool = False) -> None:
        self.registry_version = registry_version
        self.allow_conflicts = allow_conflicts
        self._records: dict[str, TermMappingRecord] = {}

    def add(self, record: TermMappingRecord) -> None:
        prepared = prepare_mapping_record(record, default_registry_version=self.registry_version)
        if not self.allow_conflicts:
            conflict = self._confirmed_conflict(prepared)
            if conflict is not None:
                raise TermRegistryConflictError(
                    f"conflicting confirmed mapping for {prepared.source_term!r}: {conflict.canonical_term!r} vs {prepared.canonical_term!r}"
                )
        self._records[prepared.term_mapping_id] = prepared

    def extend(self, records: list[TermMappingRecord]) -> None:
        for record in records:
            self.add(record)

    def records(self) -> list[TermMappingRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def by_id(self, term_mapping_id: str) -> TermMappingRecord | None:
        return self._records.get(term_mapping_id)

    def find_by_source_lexical_key(self, source_key: str) -> list[TermMappingRecord]:
        return [record for record in self.records() if record.source_lexical_key == source_key]

    def aliases_for_canonical_key(self, canonical: str, *, scope: TermScope | None = None) -> list[TermMappingRecord]:
        key = canonical_key(canonical)
        rows = [record for record in self.records() if record.canonical_key == key]
        if scope is None:
            return rows
        return [record for record in rows if scope_matches(record.scope, scope)]

    def validation_report(self) -> dict[str, Any]:
        conflicts: list[dict[str, Any]] = []
        groups: dict[tuple[str, str], list[TermMappingRecord]] = {}
        for record in self.records():
            if record.status != "CONFIRMED":
                continue
            groups.setdefault((record.source_lexical_key, record.scope.without_language().scope_key()), []).append(record)
        for records in groups.values():
            canonical_terms = {record.canonical_key for record in records}
            if len(canonical_terms) > 1:
                conflicts.append({"mapping_ids": [record.term_mapping_id for record in records], "canonical_keys": sorted(canonical_terms)})
        return {
            "registry_version": self.registry_version,
            "record_count": len(self._records),
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
            "passed": not conflicts or self.allow_conflicts,
        }

    def _confirmed_conflict(self, record: TermMappingRecord) -> TermMappingRecord | None:
        if record.status != "CONFIRMED":
            return None
        for existing in self.records():
            if existing.status != "CONFIRMED":
                continue
            if existing.source_lexical_key != record.source_lexical_key:
                continue
            if existing.scope.without_language().scope_key() != record.scope.without_language().scope_key():
                continue
            if existing.canonical_key != record.canonical_key:
                return existing
        return None


def prepare_mapping_record(record: TermMappingRecord, *, default_registry_version: str = "25A-0") -> TermMappingRecord:
    source_key = record.source_lexical_key or lexical_key(record.source_term)
    canonical = record.canonical_key or canonical_key(record.canonical_term)
    now = _now()
    return TermMappingRecord(
        term_mapping_id=record.term_mapping_id or _mapping_id(record.source_term, record.canonical_term, record.scope),
        source_term=record.source_term,
        canonical_term=record.canonical_term,
        source_language=record.source_language,
        canonical_language=record.canonical_language,
        synonym_type=record.synonym_type,
        scope=record.scope.normalized(),
        confidence=float(record.confidence),
        status=record.status,
        mapping_source=record.mapping_source,
        requires_scope=bool(record.requires_scope),
        effective_from=record.effective_from,
        effective_to=record.effective_to,
        owner=record.owner,
        comments=record.comments,
        registry_version=record.registry_version or default_registry_version,
        created_at=record.created_at or now,
        updated_at=record.updated_at or now,
        source_lexical_key=source_key,
        canonical_key=canonical,
    )


def scope_matches(record_scope: TermScope, query_scope: TermScope) -> bool:
    record = record_scope.normalized()
    query = query_scope.normalized()
    for field in ("system_name", "module_code", "domain_code", "feature_key", "object_type"):
        record_value = getattr(record, field)
        if field == "system_name" and getattr(query, field) is None:
            continue
        if record_value is not None and record_value != getattr(query, field):
            return False
    if query.language_code and record.language_code and record.language_code != query.language_code:
        return False
    return True


def write_term_migration_artifact(output_dir: str | Path) -> Path:
    path = Path(output_dir) / "schema_migration_003.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    alter_lines = [f"ALTER TABLE term_mappings ADD COLUMN {name} {spec};" for name, spec in TERM_MAPPING_EXTRA_COLUMNS.items()]
    payload = "\n".join([*alter_lines, TERM_MIGRATION_003_SQL.strip(), ""])
    path.write_text(payload, encoding="utf-8")
    return path


class TermSidecarStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def apply_migration(self) -> None:
        existing = {row["name"] for row in self.conn.execute("PRAGMA table_info(term_mappings)").fetchall()}
        for column, spec in TERM_MAPPING_EXTRA_COLUMNS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE term_mappings ADD COLUMN {column} {spec}")
        self.conn.executescript(TERM_MIGRATION_003_SQL)
        if _table_exists(self.conn, "schema_migrations"):
            self.conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (migration_id, schema_version, applied_at) VALUES (?, ?, ?)",
                (TERM_MIGRATION_ID, TERM_SCHEMA_VERSION, _now()),
            )
        self.conn.commit()

    def upsert_mapping(self, record: TermMappingRecord) -> None:
        prepared = prepare_mapping_record(record)
        self.conn.execute(
            """
            INSERT OR IGNORE INTO term_mappings (
                term_mapping_id, original_term, canonical_term, language_code, domain_code, feature_key,
                object_type, confidence, mapping_status, mapping_source, created_at, source_language,
                canonical_language, synonym_type, system_name, module_code, requires_scope, registry_version,
                effective_from, effective_to, owner, comments
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prepared.term_mapping_id,
                prepared.source_term,
                prepared.canonical_term,
                prepared.source_language,
                prepared.scope.domain_code,
                prepared.scope.feature_key,
                prepared.scope.object_type,
                prepared.confidence,
                prepared.status,
                prepared.mapping_source,
                prepared.created_at,
                prepared.source_language,
                prepared.canonical_language,
                prepared.synonym_type,
                prepared.scope.system_name,
                prepared.scope.module_code,
                int(prepared.requires_scope),
                prepared.registry_version,
                prepared.effective_from,
                prepared.effective_to,
                prepared.owner,
                prepared.comments,
            ),
        )
        self.conn.commit()

    def upsert_canonical_term(self, *, canonical_term: str, language_code: str | None, scope: TermScope) -> str:
        key = canonical_key(canonical_term)
        canonical_term_id = f"ct:{_short_hash(scope.without_language().scope_key() + ':' + key)}"
        now = _now()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO canonical_terms (
                canonical_term_id, canonical_term, canonical_key, language_code, object_type, domain_code, feature_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (canonical_term_id, canonical_term, key, language_code, scope.object_type, scope.domain_code, scope.feature_key, now, now),
        )
        self.conn.commit()
        return canonical_term_id

    def upsert_alias(self, *, semantic_object_id: str, record: TermMappingRecord) -> None:
        prepared = prepare_mapping_record(record)
        self.upsert_mapping(prepared)
        self.upsert_canonical_term(canonical_term=prepared.canonical_term, language_code=prepared.canonical_language, scope=prepared.scope)
        alias_id = f"alias:{_short_hash(semantic_object_id + ':' + prepared.term_mapping_id + ':' + prepared.source_lexical_key)}"
        self.conn.execute(
            """
            INSERT OR IGNORE INTO semantic_identity_aliases (
                alias_id, semantic_object_id, term_mapping_id, original_term, lexical_key, active_flag, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (alias_id, semantic_object_id, prepared.term_mapping_id, prepared.source_term, prepared.source_lexical_key, 1, _now()),
        )
        self.conn.commit()

    def alias_snapshot(self) -> dict[str, Any]:
        aliases = [dict(row) for row in self.conn.execute("SELECT * FROM semantic_identity_aliases ORDER BY alias_id").fetchall()]
        mappings = [dict(row) for row in self.conn.execute("SELECT term_mapping_id, original_term, canonical_term, mapping_status, source_language, canonical_language, synonym_type FROM term_mappings ORDER BY term_mapping_id").fetchall()]
        return {"alias_count": len(aliases), "mapping_count": len(mappings), "aliases": aliases, "mappings": mappings}


def registry_to_json(registry: TermRegistry) -> str:
    return json.dumps([to_plain_dict(record) for record in registry.records()], ensure_ascii=False, sort_keys=True, indent=2)


def _mapping_id(source_term: str, canonical_term: str, scope: TermScope) -> str:
    return f"term:{_short_hash(source_term + ':' + canonical_term + ':' + scope.scope_key(include_language=True))}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
    return row is not None
