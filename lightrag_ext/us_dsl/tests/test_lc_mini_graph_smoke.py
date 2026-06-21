from __future__ import annotations

import json
import os

import pytest

from lightrag_ext.us_dsl.kg_metadata_sidecar import (
    build_graph_insert_sidecar_records,
    validate_graph_insert_sidecar_alignment,
)
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload, KgEntity
from lightrag_ext.us_dsl.kg_schema_policy import FORBIDDEN_RELATION_TYPES
from lightrag_ext.us_dsl.lc_mini_graph_smoke import (
    ENABLE_LC_MINI_SMOKE_ENV,
    EXPECTED_SOURCE_TEXT_UNIT_COUNT,
    EXPECTED_SOURCE_US_COUNT,
    LcMiniGraphSmokeConfig,
    apply_lc_endpoint_closure,
    build_lc_mini_build_result,
    build_lc_mini_custom_kg_input,
    run_lc_mini_graph_smoke,
    serialize_lc_mini_graph_smoke_report,
)


@pytest.fixture(scope="module")
def lc_build_result():
    return build_lc_mini_build_result()


@pytest.fixture(scope="module")
def lc_payload(lc_build_result):
    return lc_build_result.payload


@pytest.fixture(scope="module")
def lc_custom_kg():
    return build_lc_mini_custom_kg_input()


def test_disabled_skips_lc_mini_graph_smoke():
    report = run_lc_mini_graph_smoke(config=LcMiniGraphSmokeConfig(enabled=False))

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_attempted is False


def test_lc_mini_payload_limits(lc_build_result):
    payload = lc_build_result.payload

    assert lc_build_result.source_us_count == EXPECTED_SOURCE_US_COUNT
    assert lc_build_result.first_us_id == "US-LCAB-001"
    assert lc_build_result.last_us_id == "US-LCAB-066"
    assert lc_build_result.source_text_unit_count == EXPECTED_SOURCE_TEXT_UNIT_COUNT
    assert len(payload.chunks) <= 5
    assert len(payload.entities) <= 10
    assert len(payload.relationships) <= 5
    assert len(payload.chunks) == 5
    assert len(payload.entities) == 10
    assert len(payload.relationships) == 5


def test_lc_mini_custom_kg_schema(lc_custom_kg):
    chunk_source_ids = {item["source_id"] for item in lc_custom_kg["chunks"]}
    entity_names = {item["entity_name"] for item in lc_custom_kg["entities"]}

    assert set(lc_custom_kg) == {"chunks", "entities", "relationships"}
    assert all(set(item) == {"content", "source_id"} for item in lc_custom_kg["chunks"])
    assert all(
        set(item) == {"entity_name", "entity_type", "description", "source_id"}
        for item in lc_custom_kg["entities"]
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
        for item in lc_custom_kg["relationships"]
    )
    assert all(item["source_id"] in chunk_source_ids for item in lc_custom_kg["entities"])
    assert all(
        item["source_id"] in chunk_source_ids
        for item in lc_custom_kg["relationships"]
    )
    assert all(item["src_id"] in entity_names for item in lc_custom_kg["relationships"])
    assert all(item["tgt_id"] in entity_names for item in lc_custom_kg["relationships"])
    assert all("metadata" not in item for values in lc_custom_kg.values() for item in values)
    assert all("DSL_CONTEXT" not in item["content"] for item in lc_custom_kg["chunks"])


def test_lc_mini_endpoint_closure(lc_payload):
    relationship = lc_payload.relationships[0]
    entities, relationships, dangling_count = apply_lc_endpoint_closure(
        lc_payload,
        [relationship],
        max_entities=2,
        max_relationships=1,
    )

    entity_names = {entity.entity_name for entity in entities}
    assert dangling_count == 0
    assert len(relationships) == 1
    assert relationship.src_id in entity_names
    assert relationship.tgt_id in entity_names

    broken_payload = DslKgPayload(
        chunks=[],
        entities=[
            KgEntity(
                entity_name=relationship.src_id,
                entity_type="TaskRule",
                description="source",
                source_id=relationship.source_id,
                metadata=dict(relationship.metadata),
            )
        ],
        relationships=[relationship],
    )
    broken_entities, broken_relationships, broken_dangling_count = apply_lc_endpoint_closure(
        broken_payload,
        [relationship],
        max_entities=2,
        max_relationships=1,
    )

    assert broken_entities == []
    assert broken_relationships == []
    assert broken_dangling_count == 1


def test_lc_mini_excludes_review_required_info_only_confirmed():
    report = run_lc_mini_graph_smoke(config=LcMiniGraphSmokeConfig(enabled=False))

    assert report.review_required_written is False
    assert report.info_only_written is False
    assert report.confirmed_count == 0


def test_lc_mini_blocks_forbidden_relations(lc_payload):
    assert FORBIDDEN_RELATION_TYPES.isdisjoint(
        {relationship.keywords for relationship in lc_payload.relationships}
    )


def test_lc_mini_sidecar_alignment(lc_payload, lc_custom_kg):
    records = build_graph_insert_sidecar_records(
        lc_payload,
        lc_custom_kg,
        namespace="dsl_test_lc_mini_graph_smoke",
    )
    alignment = validate_graph_insert_sidecar_alignment(lc_custom_kg, records)
    custom_object_count = (
        len(lc_custom_kg["chunks"])
        + len(lc_custom_kg["entities"])
        + len(lc_custom_kg["relationships"])
    )

    assert len(records) == custom_object_count
    assert len(records) == 20
    assert alignment.pass_status == "PASS"


def test_lc_mini_default_no_real_write(monkeypatch):
    monkeypatch.delenv(ENABLE_LC_MINI_SMOKE_ENV, raising=False)

    report = run_lc_mini_graph_smoke(config=LcMiniGraphSmokeConfig.from_env())

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_attempted is False


def test_lc_mini_real_smoke_if_enabled():
    if os.getenv(ENABLE_LC_MINI_SMOKE_ENV) != "1":
        pytest.skip("LC mini graph smoke is opt-in only.")

    report = run_lc_mini_graph_smoke(config=LcMiniGraphSmokeConfig.from_env())
    if report.skipped:
        pytest.skip(report.skip_reason or "LC mini graph smoke skipped.")

    assert report.source_us_count == 66
    assert report.source_text_unit_count == 291
    assert report.selected_chunk_count <= 5
    assert report.selected_entity_count <= 10
    assert report.selected_relationship_count <= 5
    assert report.sidecar_record_count == (
        report.selected_chunk_count
        + report.selected_entity_count
        + report.selected_relationship_count
    )
    assert report.sidecar_alignment_passed is True
    assert report.dangling_relationship_count == 0
    assert report.ainsert_custom_kg_called is True
    assert report.graph_write_succeeded is True
    assert report.neo4j_connected is False
    assert report.cleanup_passed is True


def test_report_serializable():
    report = run_lc_mini_graph_smoke(config=LcMiniGraphSmokeConfig(enabled=False))

    json.dumps(serialize_lc_mini_graph_smoke_report(report))


def test_lc_file_missing_reports_skip(tmp_path):
    report = run_lc_mini_graph_smoke(
        config=LcMiniGraphSmokeConfig(
            enabled=True,
            lc_file_path=str(tmp_path / "missing_lc.md"),
        )
    )

    assert report.skipped is True
    assert report.skip_reason == "LC_FIXTURE_NOT_FOUND"
    assert report.ainsert_custom_kg_called is False
    assert report.graph_write_attempted is False


def test_no_lc_full_write(lc_build_result):
    payload = lc_build_result.payload

    assert lc_build_result.source_text_unit_count == 291
    assert len(payload.chunks) <= 5
    assert len(payload.entities) <= 10
    assert len(payload.relationships) <= 5
    assert len(payload.chunks) < lc_build_result.source_text_unit_count
