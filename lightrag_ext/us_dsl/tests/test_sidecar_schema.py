from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lightrag_ext.us_dsl.sidecar_schema import REQUIRED_TABLES, write_schema_artifact
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def _repo() -> SQLiteSidecarRepository:
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()
    return repo


def test_schema_creates_all_required_tables():
    repo = _repo()
    tables = {row["name"] for row in repo._all("SELECT name FROM sqlite_master WHERE type = 'table'", ())}

    assert set(REQUIRED_TABLES).issubset(tables)
    assert len(REQUIRED_TABLES) == 16


def test_foreign_keys_are_enabled():
    repo = _repo()

    assert repo.foreign_keys_enabled() is True


def test_unique_constraints_exist():
    repo = _repo()
    doc_indexes = repo._all("PRAGMA index_list(documents)", ())
    version_indexes = repo._all("PRAGMA index_list(document_versions)", ())

    assert any(row["unique"] for row in doc_indexes)
    assert any(row["unique"] for row in version_indexes)


def test_graph_mapping_requires_exactly_one_semantic_target():
    repo = _repo()
    with pytest.raises(sqlite3.IntegrityError):
        repo._execute(
            """
            INSERT INTO graph_object_mappings (mapping_id, batch_id, graph_space, graph_namespace, graph_object_kind, graph_object_id, semantic_object_id, semantic_relation_id, rollback_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("m", "missing-batch", "PFSS", "pfss_test", "node", "node-1", None, None, "rb", "now"),
        )


def test_evidence_mapping_requires_exactly_one_semantic_target():
    repo = _repo()
    with pytest.raises(sqlite3.IntegrityError):
        repo._execute(
            """
            INSERT INTO evidence_mappings (evidence_mapping_id, semantic_object_id, semantic_relation_id, text_unit_id, source_span_json, text_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("ev", None, None, "tu-missing", "{}", "hash", "now"),
        )


def test_schema_sql_artifact_is_generated(tmp_path: Path):
    path = write_schema_artifact(tmp_path)

    assert path.exists()
    assert "CREATE TABLE IF NOT EXISTS documents" in path.read_text(encoding="utf-8")
