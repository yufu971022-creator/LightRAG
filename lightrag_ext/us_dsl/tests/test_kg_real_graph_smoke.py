from __future__ import annotations

import json
import os

import pytest

from lightrag_ext.us_dsl.kg_metadata_sidecar import (
    build_graph_insert_sidecar_records,
    validate_graph_insert_sidecar_alignment,
)
from lightrag_ext.us_dsl.kg_real_graph_smoke import (
    ENABLE_REAL_SMOKE_ENV,
    RealCustomKgSmokeConfig,
    build_minimal_real_smoke_custom_kg_input,
    build_minimal_real_smoke_payload,
    run_real_custom_kg_smoke,
    serialize_real_graph_smoke_report,
    without_graph_remote_env,
)
from lightrag_ext.us_dsl.kg_test_graph_write import (
    TestGraphWriteConfig,
    run_test_graph_write_dry_run,
    to_lightrag_custom_kg_input,
)


def test_disabled_skips_real_smoke():
    report = run_real_custom_kg_smoke(config=RealCustomKgSmokeConfig(enabled=False))

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_attempted is False


def test_minimal_custom_kg_schema():
    custom_kg = build_minimal_real_smoke_custom_kg_input()

    assert len(custom_kg["chunks"]) == 1
    assert len(custom_kg["entities"]) <= 2
    assert len(custom_kg["relationships"]) == 1
    assert custom_kg["chunks"][0] == {
        "content": (
            "Test source text for DSL-aware graph smoke. "
            "Field Deal Number is a required field."
        ),
        "source_id": "dsl_test_chunk_001",
    }
    chunk_source_ids = {item["source_id"] for item in custom_kg["chunks"]}
    assert all(item["source_id"] in chunk_source_ids for item in custom_kg["entities"])
    assert all(
        item["source_id"] in chunk_source_ids for item in custom_kg["relationships"]
    )
    assert {item["entity_name"] for item in custom_kg["entities"]} == {
        "TestFeature",
        "Deal Number",
    }
    assert custom_kg["relationships"][0]["keywords"] == "HasFieldSpec"
    assert "metadata" not in custom_kg["chunks"][0]
    assert "metadata" not in custom_kg["entities"][0]
    assert "metadata" not in custom_kg["relationships"][0]


def test_minimal_sidecar_alignment():
    payload = build_minimal_real_smoke_payload()
    custom_kg = to_lightrag_custom_kg_input(payload, max_entities=2, max_relationships=1)
    records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace="dsl_test_real_custom_kg_smoke",
    )
    alignment = validate_graph_insert_sidecar_alignment(custom_kg, records)

    assert len(records) == (
        len(custom_kg["chunks"])
        + len(custom_kg["entities"])
        + len(custom_kg["relationships"])
    )
    assert len(records) == 4
    assert alignment.pass_status == "PASS"


def test_blocks_production_namespace():
    report = run_real_custom_kg_smoke(
        config=RealCustomKgSmokeConfig(
            enabled=True,
            namespace="production",
            workspace="production",
        )
    )

    assert report.skipped is True
    assert report.skip_reason == "PRODUCTION_NAMESPACE_BLOCKED"
    assert report.production_namespace_blocked is True
    assert report.ainsert_custom_kg_called is False


def test_without_graph_remote_env_restores_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://production.example:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret-production-password")

    with without_graph_remote_env() as isolation:
        assert os.getenv("NEO4J_URI") is None
        assert os.getenv("NEO4J_PASSWORD") is None
        assert os.getenv("GRAPH_STORAGE") == "NetworkXStorage"
        assert isolation.isolated_graph_env_count >= 2

    assert os.getenv("NEO4J_URI") == "bolt://production.example:7687"
    assert os.getenv("NEO4J_PASSWORD") == "secret-production-password"


def test_force_local_graph_storage_config():
    config = RealCustomKgSmokeConfig(enabled=False)

    assert config.force_local_graph_storage is True
    assert config.allow_neo4j is False
    assert config.local_graph_storage == "NetworkXStorage"
    assert config.isolate_remote_graph_env is True


def test_blocks_if_local_graph_storage_not_enforced():
    report = run_real_custom_kg_smoke(
        config=RealCustomKgSmokeConfig(
            enabled=True,
            force_local_graph_storage=False,
        )
    )

    assert report.skipped is True
    assert report.skip_reason == "REAL_GRAPH_STORAGE_UNSUPPORTED"
    assert report.ainsert_custom_kg_called is False


def test_blocks_neo4j_when_not_allowed_without_isolation(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://production.example:7687")

    report = run_real_custom_kg_smoke(
        config=RealCustomKgSmokeConfig(
            enabled=True,
            allow_neo4j=False,
            isolate_remote_graph_env=False,
        )
    )

    assert report.skipped is True
    assert report.skip_reason == "NEO4J_BLOCKED"
    assert report.neo4j_connected is False
    assert report.ainsert_custom_kg_called is False


def test_no_neo4j_connected_even_if_env_present(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://production.example:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret-production-password")

    report = run_real_custom_kg_smoke(
        config=RealCustomKgSmokeConfig(
            enabled=True,
            allow_neo4j=False,
            isolate_remote_graph_env=True,
            use_temp_working_dir=False,
        )
    )

    assert report.neo4j_connected is False
    assert report.skip_reason != "NEO4J_BLOCKED"
    assert report.ainsert_custom_kg_called is False
    assert os.getenv("NEO4J_URI") == "bolt://production.example:7687"


def test_fake_lightrag_still_passes():
    fake = FakeLightRAG()
    payload = build_minimal_real_smoke_payload()

    report = run_test_graph_write_dry_run(
        payload,
        lightrag_client=fake,
        config=TestGraphWriteConfig(
            enabled=True,
            write_graph=True,
            namespace="dsl_test_real_custom_kg_fake",
            max_entities=2,
            max_relationships=1,
            cleanup_after_run=False,
            rollback_after_run=False,
        ),
    )

    assert report.skipped is False
    assert report.ainsert_custom_kg_called is True
    assert fake.called is True
    assert report.graph_insert_sidecar_record_count == 4
    assert report.graph_insert_sidecar_alignment_status == "PASS"
    assert fake.custom_kg["relationships"][0]["keywords"] == "HasFieldSpec"


def test_real_smoke_opt_in(monkeypatch):
    monkeypatch.delenv(ENABLE_REAL_SMOKE_ENV, raising=False)

    report = run_real_custom_kg_smoke(config=RealCustomKgSmokeConfig.from_env())

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_attempted is False


def test_report_serializable():
    report = run_real_custom_kg_smoke(config=RealCustomKgSmokeConfig(enabled=False))

    json.dumps(serialize_real_graph_smoke_report(report))


def test_real_custom_kg_smoke_if_enabled():
    if os.getenv(ENABLE_REAL_SMOKE_ENV) != "1":
        pytest.skip("Real custom_kg smoke is opt-in only.")

    report = run_real_custom_kg_smoke(config=RealCustomKgSmokeConfig.from_env())
    if report.skipped:
        pytest.skip(report.skip_reason or "Real custom_kg smoke skipped.")

    assert report.custom_kg_chunk_count == 1
    assert report.custom_kg_entity_count <= 2
    assert report.custom_kg_relationship_count == 1
    assert report.sidecar_record_count == (
        report.custom_kg_chunk_count
        + report.custom_kg_entity_count
        + report.custom_kg_relationship_count
    )
    assert report.sidecar_alignment_passed is True
    assert report.ainsert_custom_kg_called is True
    assert report.graph_write_succeeded is True
    assert report.neo4j_connected is False
    assert report.cleanup_passed is True


def test_real_custom_kg_smoke_with_isolated_env_if_enabled():
    if os.getenv(ENABLE_REAL_SMOKE_ENV) != "1":
        pytest.skip("Real custom_kg smoke is opt-in only.")

    report = run_real_custom_kg_smoke(
        config=RealCustomKgSmokeConfig(
            enabled=True,
            allow_neo4j=False,
            force_local_graph_storage=True,
            isolate_remote_graph_env=True,
        )
    )
    if report.skipped:
        assert report.skip_reason != "NEO4J_BLOCKED"
        pytest.skip(report.skip_reason or "Real custom_kg smoke skipped.")

    assert report.custom_kg_chunk_count == 1
    assert report.custom_kg_entity_count == 2
    assert report.custom_kg_relationship_count == 1
    assert report.sidecar_record_count == 4
    assert report.sidecar_alignment_passed is True
    assert report.ainsert_custom_kg_called is True
    assert report.graph_write_attempted is True
    assert report.graph_write_succeeded is True
    assert report.neo4j_connected is False
    assert report.cleanup_passed is True
    assert report.graph_storage_type == "NetworkXStorage"
    assert report.recommended_next_step == "TRY_FX_MINI_GRAPH_SMOKE"


class FakeLightRAG:
    def __init__(self) -> None:
        self.called = False
        self.custom_kg = None
        self.full_doc_id = None
        self.neo4j_write_called = False

    async def ainsert_custom_kg(self, custom_kg, full_doc_id=None) -> None:
        self.called = True
        self.custom_kg = custom_kg
        self.full_doc_id = full_doc_id
