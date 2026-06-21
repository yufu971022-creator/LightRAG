from __future__ import annotations

import json
import os

import pytest

from lightrag_ext.us_dsl.fx_mini_graph_smoke import (
    ENABLE_FX_MINI_SMOKE_ENV,
    FxMiniGraphSmokeConfig,
    build_fx_mini_custom_kg_input,
    build_fx_mini_kg_payload,
    run_fx_mini_graph_smoke,
    serialize_fx_mini_graph_smoke_report,
)
from lightrag_ext.us_dsl.kg_metadata_sidecar import (
    build_graph_insert_sidecar_records,
    validate_graph_insert_sidecar_alignment,
)
from lightrag_ext.us_dsl.kg_schema_policy import FORBIDDEN_RELATION_TYPES


def test_disabled_skips_fx_mini_graph_smoke():
    report = run_fx_mini_graph_smoke(config=FxMiniGraphSmokeConfig(enabled=False))

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_attempted is False


def test_fx_mini_payload_limits():
    payload = build_fx_mini_kg_payload()

    assert len(payload.chunks) <= 3
    assert len(payload.entities) <= 5
    assert len(payload.relationships) <= 3
    assert len(payload.chunks) == 3
    assert len(payload.entities) == 5
    assert len(payload.relationships) == 3


def test_fx_mini_custom_kg_schema():
    custom_kg = build_fx_mini_custom_kg_input()
    chunk_source_ids = {item["source_id"] for item in custom_kg["chunks"]}
    entity_names = {item["entity_name"] for item in custom_kg["entities"]}

    assert set(custom_kg) == {"chunks", "entities", "relationships"}
    assert all(set(item) == {"content", "source_id"} for item in custom_kg["chunks"])
    assert all(
        set(item) == {"entity_name", "entity_type", "description", "source_id"}
        for item in custom_kg["entities"]
    )
    assert all(
        set(item) == {
            "src_id",
            "tgt_id",
            "description",
            "keywords",
            "source_id",
            "weight",
        }
        for item in custom_kg["relationships"]
    )
    assert all(item["source_id"] in chunk_source_ids for item in custom_kg["entities"])
    assert all(
        item["source_id"] in chunk_source_ids for item in custom_kg["relationships"]
    )
    assert all(item["src_id"] in entity_names for item in custom_kg["relationships"])
    assert all(item["tgt_id"] in entity_names for item in custom_kg["relationships"])
    assert all("metadata" not in item for values in custom_kg.values() for item in values)


def test_fx_mini_excludes_review_required_info_only_confirmed():
    report = run_fx_mini_graph_smoke(config=FxMiniGraphSmokeConfig(enabled=False))

    assert report.review_required_written is False
    assert report.info_only_written is False
    assert report.confirmed_count == 0


def test_fx_mini_blocks_forbidden_relations():
    payload = build_fx_mini_kg_payload()

    assert FORBIDDEN_RELATION_TYPES.isdisjoint(
        {relationship.keywords for relationship in payload.relationships}
    )


def test_fx_mini_sidecar_alignment():
    payload = build_fx_mini_kg_payload()
    custom_kg = build_fx_mini_custom_kg_input()
    records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace="dsl_test_fx_mini_graph_smoke",
    )
    alignment = validate_graph_insert_sidecar_alignment(custom_kg, records)
    custom_object_count = (
        len(custom_kg["chunks"])
        + len(custom_kg["entities"])
        + len(custom_kg["relationships"])
    )

    assert len(records) == custom_object_count
    assert len(records) == 11
    assert alignment.pass_status == "PASS"


def test_fx_mini_default_no_real_write(monkeypatch):
    monkeypatch.delenv(ENABLE_FX_MINI_SMOKE_ENV, raising=False)

    report = run_fx_mini_graph_smoke(config=FxMiniGraphSmokeConfig.from_env())

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_attempted is False


def test_fx_mini_real_smoke_if_enabled():
    if os.getenv(ENABLE_FX_MINI_SMOKE_ENV) != "1":
        pytest.skip("FX mini graph smoke is opt-in only.")

    report = run_fx_mini_graph_smoke(config=FxMiniGraphSmokeConfig.from_env())
    if report.skipped:
        pytest.skip(report.skip_reason or "FX mini graph smoke skipped.")

    assert report.selected_chunk_count <= 3
    assert report.selected_entity_count <= 5
    assert report.selected_relationship_count <= 3
    assert report.sidecar_record_count == (
        report.selected_chunk_count
        + report.selected_entity_count
        + report.selected_relationship_count
    )
    assert report.sidecar_alignment_passed is True
    assert report.ainsert_custom_kg_called is True
    assert report.graph_write_succeeded is True
    assert report.neo4j_connected is False
    assert report.cleanup_passed is True
    assert report.recommended_next_step == "TRY_LC_MINI_GRAPH_SMOKE"


def test_report_serializable():
    report = run_fx_mini_graph_smoke(config=FxMiniGraphSmokeConfig(enabled=False))

    json.dumps(serialize_fx_mini_graph_smoke_report(report))
