from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .sidecar_registry_types import IngestionBatchRecord, SidecarPersistenceBundle, TABLE_COUNT_KEYS
from .sidecar_schema import (
    ALL_TABLES,
    LIFECYCLE_MIGRATION_ID,
    LIFECYCLE_REQUIRED_TABLES,
    LIFECYCLE_SCHEMA_VERSION,
    MIGRATION_002_SQL,
    SCHEMA_SQL,
)


class SidecarPathError(ValueError):
    pass


class SQLiteSidecarRepository:
    def __init__(self, db_path: str, *, artifact_root: str | None = None) -> None:
        self.db_path = db_path
        self.artifact_root = artifact_root
        validate_database_path(db_path, artifact_root=artifact_root)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self._conn.close()

    def initialize_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def apply_lifecycle_migration(self) -> None:
        self._conn.executescript(MIGRATION_002_SQL)
        self._execute(
            """
            INSERT OR IGNORE INTO schema_migrations (migration_id, schema_version, applied_at)
            VALUES (?, ?, ?)
            """,
            (LIFECYCLE_MIGRATION_ID, LIFECYCLE_SCHEMA_VERSION, _now()),
        )
        self._conn.commit()

    def foreign_keys_enabled(self) -> bool:
        return bool(self._conn.execute("PRAGMA foreign_keys").fetchone()[0])

    def begin_batch(self, batch: IngestionBatchRecord) -> None:
        row = _batch_row(batch)
        self._execute(
            """
            INSERT INTO ingestion_batches (
                batch_id, trace_id, requested_mode, semantic_route, status,
                policy_version, ontology_version, term_registry_version, pfss_namespace,
                started_at, completed_at, error_code, error_summary, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["batch_id"], row["trace_id"], row["requested_mode"], row["semantic_route"], row["status"],
                row["policy_version"], row["ontology_version"], row["term_registry_version"], row["pfss_namespace"],
                row["started_at"], row["completed_at"], row["error_code"], row["error_summary"], None,
            ),
        )
        self._conn.commit()

    def persist_bundle(self, bundle: SidecarPersistenceBundle) -> None:
        with self._transaction():
            self._upsert_document(bundle.document)
            self._upsert_document_version(bundle.document_version)
            self._execute(
                "INSERT OR IGNORE INTO batch_documents (batch_id, document_version_id) VALUES (?, ?)",
                (bundle.batch.batch_id, bundle.document_version["document_version_id"]),
            )
            for item in bundle.raw_chunks:
                self._upsert_raw_chunk(item)
            for item in bundle.source_text_units:
                self._upsert_source_text_unit(item)
            for item in bundle.chunk_text_unit_links:
                self._upsert_chunk_text_unit_link(item)
            for item in bundle.semantic_objects:
                self._upsert_semantic_object(item)
            for item in bundle.semantic_relations:
                self._upsert_semantic_relation(item)
            if bundle.fail_after_semantic_relations:
                raise RuntimeError("injected_failure_after_semantic_relations")
            for item in bundle.graph_object_mappings:
                self._upsert_graph_object_mapping(item)
            for item in bundle.evidence_mappings:
                self._upsert_evidence_mapping(item)
            for item in bundle.term_mappings:
                self._upsert_term_mapping(item)
            for item in bundle.version_groups:
                self._upsert_version_group(item)
            for item in bundle.version_members:
                self._upsert_version_member(item)
            for item in bundle.issues:
                self._upsert_issue(item)
            for item in bundle.rollback_records:
                self._upsert_rollback_record(item)

    def complete_batch(self, batch_id: str, summary: dict[str, Any]) -> None:
        self._execute(
            "UPDATE ingestion_batches SET status = ?, completed_at = ?, summary_json = ? WHERE batch_id = ?",
            ("COMPLETED", _now(), json.dumps(summary, sort_keys=True), batch_id),
        )
        self._conn.commit()

    def fail_batch(self, batch_id: str, error: dict[str, Any]) -> None:
        self._execute(
            "UPDATE ingestion_batches SET status = ?, completed_at = ?, error_code = ?, error_summary = ?, summary_json = ? WHERE batch_id = ?",
            ("FAILED", _now(), error.get("code", "FAILED"), error.get("summary", "failure"), json.dumps(error, sort_keys=True), batch_id),
        )
        self._conn.commit()

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM documents WHERE document_id = ?", (document_id,))

    def get_document_version(self, document_version_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM document_versions WHERE document_version_id = ?", (document_version_id,))

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM ingestion_batches WHERE batch_id = ?", (batch_id,))

    def get_batch_by_trace_id(self, trace_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM ingestion_batches WHERE trace_id = ?", (trace_id,))

    def list_source_text_units(self, document_version_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM source_text_units WHERE document_version_id = ? ORDER BY start_offset", (document_version_id,))

    def list_semantic_objects(self, document_version_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM semantic_objects WHERE document_version_id = ? ORDER BY semantic_object_id", (document_version_id,))

    def list_semantic_relations(self, document_version_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM semantic_relations WHERE document_version_id = ? ORDER BY semantic_relation_id", (document_version_id,))

    def list_evidence_for_object(self, semantic_object_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM evidence_mappings WHERE semantic_object_id = ? ORDER BY evidence_mapping_id", (semantic_object_id,))

    def list_issues(self, document_version_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM ingestion_issues WHERE document_version_id = ? ORDER BY issue_id", (document_version_id,))

    def get_rollback_manifest(self, batch_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM rollback_records WHERE batch_id = ? ORDER BY rollback_record_id", (batch_id,))

    def list_graph_mappings(self, document_version_id: str) -> list[dict[str, Any]]:
        return self._all(
            """
            SELECT gm.* FROM graph_object_mappings gm
            LEFT JOIN semantic_objects so ON gm.semantic_object_id = so.semantic_object_id
            LEFT JOIN semantic_relations sr ON gm.semantic_relation_id = sr.semantic_relation_id
            WHERE so.document_version_id = ? OR sr.document_version_id = ?
            ORDER BY gm.graph_object_kind, gm.graph_object_id
            """,
            (document_version_id, document_version_id),
        )

    def trace_graph_object(self, graph_space: str, graph_namespace: str, graph_object_kind: str, graph_object_id: str) -> dict[str, Any] | None:
        mapping = self._one(
            """
            SELECT * FROM graph_object_mappings
            WHERE graph_space = ? AND graph_namespace = ? AND graph_object_kind = ? AND graph_object_id = ?
            """,
            (graph_space, graph_namespace, graph_object_kind, graph_object_id),
        )
        if not mapping:
            return None
        if mapping.get("semantic_object_id"):
            semantic = self._one("SELECT * FROM semantic_objects WHERE semantic_object_id = ?", (mapping["semantic_object_id"],))
            evidence = self.list_evidence_for_object(mapping["semantic_object_id"])
        else:
            semantic = self._one("SELECT * FROM semantic_relations WHERE semantic_relation_id = ?", (mapping["semantic_relation_id"],))
            evidence = self._all("SELECT * FROM evidence_mappings WHERE semantic_relation_id = ? ORDER BY evidence_mapping_id", (mapping["semantic_relation_id"],))
        document_version = self.get_document_version(semantic["document_version_id"]) if semantic else None
        document = self.get_document(document_version["document_id"]) if document_version else None
        first_evidence = evidence[0] if evidence else None
        text_unit = self._one("SELECT * FROM source_text_units WHERE text_unit_id = ?", (first_evidence["text_unit_id"],)) if first_evidence else None
        return {
            "mapping": mapping,
            "semantic": semantic,
            "document": document,
            "document_version": document_version,
            "evidence": evidence,
            "source_us_id": text_unit.get("source_us_id") if text_unit else None,
            "text_unit_id": text_unit.get("text_unit_id") if text_unit else None,
            "source_span_json": first_evidence.get("source_span_json") if first_evidence else None,
            "text_hash": first_evidence.get("text_hash") if first_evidence else None,
            "evidence_excerpt": first_evidence.get("evidence_excerpt") if first_evidence else None,
            "version_status": semantic.get("knowledge_status") if semantic else None,
            "review_decision": semantic.get("review_decision") if semantic else None,
        }

    def version_group(self, version_group_key: str) -> dict[str, Any]:
        group = self._one("SELECT * FROM version_groups WHERE version_group_key = ?", (version_group_key,))
        members = self._all("SELECT * FROM version_members WHERE version_group_key = ? ORDER BY version_member_id", (version_group_key,))
        issues = []
        for member in members:
            issues.extend(self._all("SELECT * FROM ingestion_issues WHERE semantic_object_id = ? ORDER BY issue_id", (member["semantic_object_id"],)))
        return {"group": group, "members": members, "issues": issues}

    def count_table(self, table: str) -> int:
        if table not in ALL_TABLES:
            raise ValueError(f"Unsupported table: {table}")
        return int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def record_counts(self) -> dict[str, int]:
        return {alias: self.count_table(table) for table, alias in TABLE_COUNT_KEYS.items()}

    def validate_referential_integrity(self) -> dict[str, Any]:
        rows = self._conn.execute("PRAGMA foreign_key_check").fetchall()
        orphan_relations = self._conn.execute(
            """
            SELECT COUNT(*) FROM semantic_relations sr
            LEFT JOIN semantic_objects src ON sr.src_semantic_object_id = src.semantic_object_id
            LEFT JOIN semantic_objects tgt ON sr.tgt_semantic_object_id = tgt.semantic_object_id
            WHERE src.semantic_object_id IS NULL OR tgt.semantic_object_id IS NULL
            """
        ).fetchone()[0]
        return {
            "foreign_key_check_passed": len(rows) == 0,
            "foreign_key_violations": [dict(row) for row in rows],
            "orphan_relation_count": int(orphan_relations),
            "passed": len(rows) == 0 and int(orphan_relations) == 0,
        }

    def lifecycle_tables_present(self) -> bool:
        tables = {
            row["name"]
            for row in self._all(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (%s)"
                % ",".join("?" for _ in LIFECYCLE_REQUIRED_TABLES),
                tuple(LIFECYCLE_REQUIRED_TABLES),
            )
        }
        return set(LIFECYCLE_REQUIRED_TABLES).issubset(tables)

    def set_document_active_version(self, document_id: str, active_document_version_id: str | None, batch_id: str) -> None:
        self._execute(
            """
            INSERT INTO document_active_versions (document_id, active_document_version_id, updated_by_batch_id, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                active_document_version_id = excluded.active_document_version_id,
                updated_by_batch_id = excluded.updated_by_batch_id,
                updated_at = excluded.updated_at
            """,
            (document_id, active_document_version_id, batch_id, _now()),
        )
        self._conn.commit()

    def get_active_version(self, document_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM document_active_versions WHERE document_id = ?", (document_id,))

    def update_document_version_status(self, document_version_id: str, status: str) -> None:
        self._execute(
            "UPDATE document_versions SET status = ? WHERE document_version_id = ?",
            (status, document_version_id),
        )
        self._conn.commit()

    def record_version_state(self, document_version_id: str, old_status: str | None, new_status: str, batch_id: str, reason_code: str) -> None:
        self._execute(
            """
            INSERT OR IGNORE INTO document_version_state_history (
                state_history_id, document_version_id, old_status, new_status, batch_id, reason_code, changed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"state:{document_version_id}:{batch_id}:{new_status}",
                document_version_id,
                old_status,
                new_status,
                batch_id,
                reason_code,
                _now(),
            ),
        )
        self._conn.commit()

    def list_version_state_history(self, document_version_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM document_version_state_history WHERE document_version_id = ? ORDER BY changed_at, state_history_id",
            (document_version_id,),
        )

    def upsert_raw_chunk_contribution(self, item: dict[str, Any]) -> None:
        self._upsert_contribution("raw_chunk_contributions", "chunk_id", item)

    def upsert_semantic_object_contribution(self, item: dict[str, Any]) -> None:
        self._upsert_contribution("semantic_object_contributions", "semantic_object_id", item)

    def upsert_semantic_relation_contribution(self, item: dict[str, Any]) -> None:
        self._upsert_contribution("semantic_relation_contributions", "semantic_relation_id", item)

    def deactivate_version_contributions(self, document_version_id: str, batch_id: str) -> None:
        for table in ("raw_chunk_contributions", "semantic_object_contributions", "semantic_relation_contributions"):
            self._execute(
                f"""
                UPDATE {table}
                SET active_flag = 0, deactivated_by_batch_id = ?, updated_at = ?
                WHERE document_version_id = ? AND active_flag = 1
                """,
                (batch_id, _now(), document_version_id),
            )
        self._conn.commit()

    def active_chunk_contribution_count(self, chunk_id: str) -> int:
        return self._active_contribution_count("raw_chunk_contributions", "chunk_id", chunk_id)

    def active_object_contribution_count(self, semantic_object_id: str) -> int:
        return self._active_contribution_count("semantic_object_contributions", "semantic_object_id", semantic_object_id)

    def active_relation_contribution_count(self, semantic_relation_id: str) -> int:
        return self._active_contribution_count("semantic_relation_contributions", "semantic_relation_id", semantic_relation_id)

    def list_active_contributions(self, table: str) -> list[dict[str, Any]]:
        if table not in {"raw_chunk_contributions", "semantic_object_contributions", "semantic_relation_contributions"}:
            raise ValueError(f"Unsupported contribution table: {table}")
        return self._all(f"SELECT * FROM {table} WHERE active_flag = 1 ORDER BY contribution_id")

    def list_contributions_for_version(self, document_version_id: str) -> dict[str, list[dict[str, Any]]]:
        return {
            "raw_chunks": self._all("SELECT * FROM raw_chunk_contributions WHERE document_version_id = ? ORDER BY chunk_id", (document_version_id,)),
            "semantic_objects": self._all("SELECT * FROM semantic_object_contributions WHERE document_version_id = ? ORDER BY semantic_object_id", (document_version_id,)),
            "semantic_relations": self._all("SELECT * FROM semantic_relation_contributions WHERE document_version_id = ? ORDER BY semantic_relation_id", (document_version_id,)),
        }

    def create_lifecycle_mutation(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR REPLACE INTO lifecycle_mutations (
                mutation_id, batch_id, document_id, old_document_version_id, new_document_version_id,
                operation_type, status, plan_hash, started_at, completed_at, error_code, error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["mutation_id"],
                item["batch_id"],
                item["document_id"],
                item.get("old_document_version_id"),
                item.get("new_document_version_id"),
                item["operation_type"],
                item.get("status", "PLANNED"),
                item["plan_hash"],
                item.get("started_at", _now()),
                item.get("completed_at"),
                item.get("error_code"),
                item.get("error_summary"),
            ),
        )
        self._conn.commit()

    def update_lifecycle_mutation(self, mutation_id: str, status: str, error: dict[str, Any] | None = None) -> None:
        error = error or {}
        completed_at = _now() if status in {"APPLIED", "COMPENSATED", "FAILED"} else None
        self._execute(
            """
            UPDATE lifecycle_mutations
            SET status = ?, completed_at = COALESCE(?, completed_at), error_code = ?, error_summary = ?
            WHERE mutation_id = ?
            """,
            (status, completed_at, error.get("code"), error.get("summary"), mutation_id),
        )
        self._conn.commit()

    def insert_lifecycle_step(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR REPLACE INTO lifecycle_mutation_steps (
                mutation_step_id, mutation_id, step_order, store_kind, operation_kind, target_kind, target_id,
                preimage_json, postimage_json, status, error_summary, executed_at, compensated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["mutation_step_id"],
                item["mutation_id"],
                item["step_order"],
                item["store_kind"],
                item["operation_kind"],
                item["target_kind"],
                item["target_id"],
                _json(item.get("preimage")) if item.get("preimage") is not None else None,
                _json(item.get("postimage")) if item.get("postimage") is not None else None,
                item.get("status", "PENDING"),
                item.get("error_summary"),
                item.get("executed_at"),
                item.get("compensated_at"),
            ),
        )
        self._conn.commit()

    def update_lifecycle_step(self, mutation_step_id: str, status: str, *, error_summary: str | None = None, compensated: bool = False) -> None:
        if compensated:
            self._execute(
                "UPDATE lifecycle_mutation_steps SET status = ?, error_summary = ?, compensated_at = ? WHERE mutation_step_id = ?",
                (status, error_summary, _now(), mutation_step_id),
            )
        else:
            self._execute(
                "UPDATE lifecycle_mutation_steps SET status = ?, error_summary = ?, executed_at = ? WHERE mutation_step_id = ?",
                (status, error_summary, _now(), mutation_step_id),
            )
        self._conn.commit()

    def list_lifecycle_steps(self, mutation_id: str) -> list[dict[str, Any]]:
        return self._all(
            "SELECT * FROM lifecycle_mutation_steps WHERE mutation_id = ? ORDER BY step_order",
            (mutation_id,),
        )

    def get_lifecycle_mutation(self, mutation_id: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM lifecycle_mutations WHERE mutation_id = ?", (mutation_id,))

    def create_tombstone(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR IGNORE INTO document_tombstones (
                tombstone_id, document_id, document_version_id, delete_scope, reason_code, deleted_by_batch_id, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["tombstone_id"],
                item["document_id"],
                item.get("document_version_id"),
                item["delete_scope"],
                item["reason_code"],
                item["deleted_by_batch_id"],
                item.get("deleted_at", _now()),
            ),
        )
        self._conn.commit()

    def list_tombstones(self, document_id: str) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM document_tombstones WHERE document_id = ? ORDER BY deleted_at, tombstone_id", (document_id,))

    def create_rebuild_request(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR REPLACE INTO rebuild_requests (
                rebuild_request_id, document_version_id, reason_code, status, requested_by_batch_id,
                completed_by_batch_id, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["rebuild_request_id"],
                item["document_version_id"],
                item["reason_code"],
                item.get("status", "REQUESTED"),
                item["requested_by_batch_id"],
                item.get("completed_by_batch_id"),
                item.get("created_at", _now()),
                item.get("completed_at"),
            ),
        )
        self._conn.commit()

    def _upsert_document(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO documents (document_id, source_uri_hash, source_type, module_code, logical_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET updated_at = excluded.updated_at, logical_name = excluded.logical_name
            """,
            (item["document_id"], item["source_uri_hash"], item.get("source_type"), item.get("module_code"), item.get("logical_name"), item["created_at"], item["updated_at"]),
        )

    def _upsert_document_version(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO document_versions (document_version_id, document_id, content_hash, parser_name, parser_version, normalized_text_hash, status, previous_version_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_version_id) DO UPDATE SET status = excluded.status
            """,
            (item["document_version_id"], item["document_id"], item["content_hash"], item.get("parser_name"), item.get("parser_version"), item.get("normalized_text_hash"), item.get("status"), item.get("previous_version_id"), item["created_at"]),
        )

    def _upsert_raw_chunk(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR IGNORE INTO raw_evidence_chunks (chunk_id, document_version_id, chunk_order, start_offset, end_offset, token_count, content_hash, source_span_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item["chunk_id"], item["document_version_id"], item["chunk_order"], item["start_offset"], item["end_offset"], item["token_count"], item["content_hash"], _json(item.get("source_span", {})), item["created_at"]),
        )

    def _upsert_source_text_unit(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR IGNORE INTO source_text_units (text_unit_id, document_version_id, source_us_id, section_type, start_offset, end_offset, text_hash, feature_key, primary_domain, related_domains_json, evidence_excerpt, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item["text_unit_id"], item["document_version_id"], item.get("source_us_id"), item.get("section_type"), item["start_offset"], item["end_offset"], item["text_hash"], item.get("feature_key"), item.get("primary_domain"), _json(item.get("related_domains", [])), item.get("evidence_excerpt"), item["created_at"]),
        )

    def _upsert_chunk_text_unit_link(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR IGNORE INTO chunk_text_unit_links (link_id, document_version_id, chunk_id, text_unit_id, overlap_start_offset, overlap_end_offset, overlap_char_count, chunk_coverage_ratio, text_unit_coverage_ratio, link_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item["link_id"], item["document_version_id"], item["chunk_id"], item["text_unit_id"], item["overlap_start_offset"], item["overlap_end_offset"], item["overlap_char_count"], item["chunk_coverage_ratio"], item["text_unit_coverage_ratio"], item["link_type"]),
        )

    def _upsert_semantic_object(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO semantic_objects (semantic_object_id, document_version_id, object_type, canonical_name, domain_code, feature_key, knowledge_status, validation_status, review_decision, version_group_key, idempotency_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET updated_at = excluded.updated_at, review_decision = excluded.review_decision
            """,
            (item["semantic_object_id"], item["document_version_id"], item["object_type"], item["canonical_name"], item.get("domain_code"), item.get("feature_key"), item.get("knowledge_status"), item.get("validation_status"), item.get("review_decision"), item.get("version_group_key"), item["idempotency_key"], item["created_at"], item["updated_at"]),
        )

    def _upsert_semantic_relation(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT INTO semantic_relations (semantic_relation_id, document_version_id, src_semantic_object_id, relation_type, tgt_semantic_object_id, knowledge_status, validation_status, review_decision, idempotency_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(idempotency_key) DO UPDATE SET updated_at = excluded.updated_at, review_decision = excluded.review_decision
            """,
            (item["semantic_relation_id"], item["document_version_id"], item["src_semantic_object_id"], item["relation_type"], item["tgt_semantic_object_id"], item.get("knowledge_status"), item.get("validation_status"), item.get("review_decision"), item["idempotency_key"], item["created_at"], item["updated_at"]),
        )

    def _upsert_graph_object_mapping(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR IGNORE INTO graph_object_mappings (mapping_id, batch_id, graph_space, graph_namespace, graph_object_kind, graph_object_id, semantic_object_id, semantic_relation_id, source_id, rollback_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item["mapping_id"], item["batch_id"], item["graph_space"], item["graph_namespace"], item["graph_object_kind"], item["graph_object_id"], item.get("semantic_object_id"), item.get("semantic_relation_id"), item.get("source_id"), item["rollback_key"], item["created_at"]),
        )

    def _upsert_evidence_mapping(self, item: dict[str, Any]) -> None:
        self._execute(
            """
            INSERT OR IGNORE INTO evidence_mappings (evidence_mapping_id, semantic_object_id, semantic_relation_id, text_unit_id, source_span_json, text_hash, evidence_excerpt, evidence_role, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item["evidence_mapping_id"], item.get("semantic_object_id"), item.get("semantic_relation_id"), item["text_unit_id"], _json(item.get("source_span", {})), item["text_hash"], item.get("evidence_excerpt"), item.get("evidence_role"), item["created_at"]),
        )

    def _upsert_term_mapping(self, item: dict[str, Any]) -> None:
        self._execute(
            "INSERT OR IGNORE INTO term_mappings (term_mapping_id, original_term, canonical_term, language_code, domain_code, feature_key, object_type, confidence, mapping_status, mapping_source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["term_mapping_id"], item["original_term"], item["canonical_term"], item.get("language_code"), item.get("domain_code"), item.get("feature_key"), item.get("object_type"), item.get("confidence"), item["mapping_status"], item.get("mapping_source"), item["created_at"]),
        )

    def _upsert_version_group(self, item: dict[str, Any]) -> None:
        self._execute(
            "INSERT OR IGNORE INTO version_groups (version_group_key, module_code, domain_code, feature_key, object_type, object_key, rule_dimension, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["version_group_key"], item.get("module_code"), item.get("domain_code"), item.get("feature_key"), item.get("object_type"), item.get("object_key"), item.get("rule_dimension"), item["created_at"], item["updated_at"]),
        )

    def _upsert_version_member(self, item: dict[str, Any]) -> None:
        self._execute(
            "INSERT OR IGNORE INTO version_members (version_member_id, version_group_key, semantic_object_id, rule_version, version_status, latest_flag, valid_from, valid_to, supersedes_member_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["version_member_id"], item["version_group_key"], item["semantic_object_id"], item.get("rule_version"), item.get("version_status"), int(item.get("latest_flag", False)), item.get("valid_from"), item.get("valid_to"), item.get("supersedes_member_id"), item["created_at"]),
        )

    def _upsert_issue(self, item: dict[str, Any]) -> None:
        self._execute(
            "INSERT OR IGNORE INTO ingestion_issues (issue_id, batch_id, document_version_id, semantic_object_id, semantic_relation_id, text_unit_id, issue_type, severity, reason_code, review_required, issue_status, evidence_excerpt, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["issue_id"], item["batch_id"], item["document_version_id"], item.get("semantic_object_id"), item.get("semantic_relation_id"), item.get("text_unit_id"), item["issue_type"], item.get("severity"), item.get("reason_code"), int(item.get("review_required", True)), item.get("issue_status", "OPEN"), item.get("evidence_excerpt"), item["created_at"], item["updated_at"]),
        )

    def _upsert_rollback_record(self, item: dict[str, Any]) -> None:
        self._execute(
            "INSERT OR IGNORE INTO rollback_records (rollback_record_id, batch_id, graph_space, graph_namespace, graph_object_kind, graph_object_id, rollback_key, planned_action, execution_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["rollback_record_id"], item["batch_id"], item["graph_space"], item["graph_namespace"], item["graph_object_kind"], item["graph_object_id"], item["rollback_key"], item["planned_action"], item["execution_status"], item["created_at"]),
        )

    def _upsert_contribution(self, table: str, id_column: str, item: dict[str, Any]) -> None:
        self._execute(
            f"""
            INSERT INTO {table} (
                contribution_id, document_version_id, {id_column}, active_flag, projection_hash,
                created_by_batch_id, deactivated_by_batch_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_version_id, {id_column}) DO UPDATE SET
                active_flag = excluded.active_flag,
                projection_hash = excluded.projection_hash,
                deactivated_by_batch_id = excluded.deactivated_by_batch_id,
                updated_at = excluded.updated_at
            """,
            (
                item["contribution_id"],
                item["document_version_id"],
                item[id_column],
                int(item.get("active_flag", True)),
                item["projection_hash"],
                item["created_by_batch_id"],
                item.get("deactivated_by_batch_id"),
                item.get("created_at", _now()),
                item.get("updated_at", _now()),
            ),
        )
        self._conn.commit()

    def _active_contribution_count(self, table: str, id_column: str, target_id: str) -> int:
        return int(
            self._conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {id_column} = ? AND active_flag = 1",
                (target_id,),
            ).fetchone()[0]
        )

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    @contextmanager
    def _transaction(self):
        try:
            self._conn.execute("BEGIN")
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()


def validate_database_path(db_path: str, *, artifact_root: str | None) -> None:
    if db_path == ":memory:":
        return
    if not artifact_root:
        raise SidecarPathError("artifact_root is required for file-backed sidecar database")
    root = (Path(artifact_root).resolve() / "workspaces").resolve()
    path = Path(db_path).resolve()
    if not str(path).startswith(str(root)):
        raise SidecarPathError("SQLite sidecar database must be inside artifact_root/workspaces")
    if path.name != "sidecar.db":
        raise SidecarPathError("SQLite sidecar database file must be named sidecar.db")


def _batch_row(batch: IngestionBatchRecord) -> dict[str, Any]:
    started = batch.started_at or _now()
    return {
        "batch_id": batch.batch_id,
        "trace_id": batch.trace_id,
        "requested_mode": batch.requested_mode,
        "semantic_route": batch.semantic_route,
        "status": batch.status,
        "policy_version": batch.policy_version,
        "ontology_version": batch.ontology_version,
        "term_registry_version": batch.term_registry_version,
        "pfss_namespace": batch.pfss_namespace,
        "started_at": started,
        "completed_at": batch.completed_at,
        "error_code": batch.error_code,
        "error_summary": batch.error_summary,
    }


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
