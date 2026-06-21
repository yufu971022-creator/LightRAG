from __future__ import annotations

import json
import os
from dataclasses import asdict, replace

import pytest

from lightrag_ext.us_dsl.kg_metadata_sidecar import (
    KgMetadataSidecarRecord,
    KgMetadataSidecarStore,
    build_graph_insert_sidecar_records,
    build_metadata_sidecar_records,
    chunk_external_key,
    entity_external_key,
    relationship_external_key,
    serialize_graph_insert_sidecar_alignment_report,
    serialize_sidecar_record,
    validate_graph_insert_sidecar_alignment,
)
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload
from lightrag_ext.us_dsl.kg_test_graph_write import (
    TestGraphWriteConfig,
    run_test_graph_write_dry_run,
    serialize_test_graph_write_report,
    to_lightrag_custom_kg_input,
)
from lightrag_ext.us_dsl.tests.test_kg_metadata_sidecar import _build_lc_kg_payload
from lightrag_ext.us_dsl.tests.test_kg_payload_mapper import _build_fx_kg_payload


def test_disabled_skips_graph_write():
    report = run_test_graph_write_dry_run(
        _build_fx_kg_payload(),
        lightrag_client=FakeLightRAG(),
        config=TestGraphWriteConfig(enabled=False),
    )

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False


def test_to_lightrag_custom_kg_input_fx():
    payload = _build_fx_kg_payload()
    custom_kg = to_lightrag_custom_kg_input(payload)

    assert set(custom_kg) == {"chunks", "entities", "relationships"}
    assert custom_kg["chunks"]
    assert custom_kg["entities"]
    assert custom_kg["relationships"]
    assert "metadata" not in custom_kg["chunks"][0]
    assert "metadata" not in custom_kg["entities"][0]
    assert "metadata" not in custom_kg["relationships"][0]
    chunk_source_ids = {item["source_id"] for item in custom_kg["chunks"]}
    assert all(item["source_id"] in chunk_source_ids for item in custom_kg["entities"])
    assert all(
        item["source_id"] in chunk_source_ids for item in custom_kg["relationships"]
    )


def test_to_lightrag_custom_kg_input_lc():
    payload = _build_lc_kg_payload()
    custom_kg = to_lightrag_custom_kg_input(
        payload,
        max_entities=50,
        max_relationships=50,
    )

    assert len(custom_kg["chunks"]) == 291
    assert len(custom_kg["entities"]) == 50
    assert len(custom_kg["relationships"]) == 50


def test_lc_full_sidecar_and_graph_insert_sidecar_are_distinct():
    payload = _build_lc_kg_payload()
    custom_kg = to_lightrag_custom_kg_input(
        payload,
        max_entities=50,
        max_relationships=50,
    )
    full_records = build_metadata_sidecar_records(payload, namespace="dsl_test_lc")
    graph_insert_records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace="dsl_test_lc",
    )
    custom_object_count = _custom_kg_object_count(custom_kg)

    assert len(full_records) > len(graph_insert_records)
    assert len(graph_insert_records) == custom_object_count


def test_graph_insert_sidecar_alignment_lc_limited_payload():
    payload = _build_lc_kg_payload()
    custom_kg = to_lightrag_custom_kg_input(
        payload,
        max_entities=50,
        max_relationships=50,
    )
    graph_insert_records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace="dsl_test_lc",
    )
    alignment = validate_graph_insert_sidecar_alignment(
        custom_kg,
        graph_insert_records,
    )

    assert len(custom_kg["chunks"]) == 291
    assert len(custom_kg["entities"]) == 50
    assert len(custom_kg["relationships"]) == 50
    assert len(graph_insert_records) == 391
    assert alignment.chunk_alignment_ratio == 1.0
    assert alignment.entity_alignment_ratio == 1.0
    assert alignment.relationship_alignment_ratio == 1.0
    assert alignment.pass_status == "PASS"


def test_graph_insert_sidecar_no_extra_records():
    payload = _build_lc_kg_payload()
    custom_kg = to_lightrag_custom_kg_input(
        payload,
        max_entities=50,
        max_relationships=50,
    )
    graph_insert_records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace="dsl_test_lc",
    )
    custom_keys = _custom_kg_external_keys(custom_kg)

    assert all(record.external_key in custom_keys for record in graph_insert_records)


def test_graph_insert_sidecar_every_custom_object_has_metadata():
    payload = _build_lc_kg_payload()
    custom_kg = to_lightrag_custom_kg_input(
        payload,
        max_entities=50,
        max_relationships=50,
    )
    graph_insert_records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace="dsl_test_lc",
    )
    records_by_key = {record.external_key: record for record in graph_insert_records}

    for key in _custom_kg_external_keys(custom_kg):
        record = records_by_key[key]
        assert record.metadata.get("sourceUsId")
        assert record.metadata.get("textUnitId")
        assert record.metadata.get("sourceSpan")
        assert record.metadata.get("textHash")
        assert record.metadata.get("knowledgeStatus")


def test_graph_insert_sidecar_serializable():
    payload = _build_lc_kg_payload()
    custom_kg = to_lightrag_custom_kg_input(
        payload,
        max_entities=50,
        max_relationships=50,
    )
    graph_insert_records = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace="dsl_test_lc",
    )
    alignment = validate_graph_insert_sidecar_alignment(
        custom_kg,
        graph_insert_records,
    )

    json.dumps(
        {
            "records": [
                serialize_sidecar_record(record) for record in graph_insert_records
            ],
            "alignment": serialize_graph_insert_sidecar_alignment_report(alignment),
        }
    )


def test_blocks_production_namespace():
    report = run_test_graph_write_dry_run(
        _build_fx_kg_payload(),
        lightrag_client=FakeLightRAG(),
        config=TestGraphWriteConfig(
            enabled=True,
            write_graph=True,
            namespace="production",
        ),
    )

    assert report.skipped is True
    assert report.production_namespace_blocked is True
    assert report.ainsert_custom_kg_called is False


def test_blocks_sidecar_coverage_failure():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")
    broken = asdict(records[0])
    broken["metadata"] = dict(broken["metadata"])
    broken["metadata"].pop("textHash", None)
    records[0] = KgMetadataSidecarRecord(**broken)

    report = run_test_graph_write_dry_run(
        payload,
        lightrag_client=FakeLightRAG(),
        config=_enabled_config(),
        sidecar_records=records,
    )

    assert report.skipped is True
    assert report.sidecar_coverage_passed is False
    assert report.ainsert_custom_kg_called is False


def test_blocks_confirmed_payload():
    payload = _payload_with_entity_status("Confirmed")

    report = run_test_graph_write_dry_run(
        payload,
        lightrag_client=FakeLightRAG(),
        config=_enabled_config(),
    )

    assert report.skipped is True
    assert report.skip_reason == "CONFIRMED_PAYLOAD_BLOCKED"
    assert report.ainsert_custom_kg_called is False


def test_blocks_forbidden_relation():
    payload = _payload_with_forbidden_relation()

    report = run_test_graph_write_dry_run(
        payload,
        lightrag_client=FakeLightRAG(),
        config=_enabled_config(),
    )

    assert report.skipped is True
    assert report.skip_reason == "FORBIDDEN_RELATION_BLOCKED"
    assert report.ainsert_custom_kg_called is False


def test_test_graph_write_with_fake_lightrag():
    fake = FakeLightRAG()

    report = run_test_graph_write_dry_run(
        _build_fx_kg_payload(),
        lightrag_client=fake,
        config=_enabled_config(cleanup_after_run=True),
    )

    assert report.skipped is False
    assert report.ainsert_custom_kg_called is True
    assert report.graph_write_called is True
    assert fake.called is True
    assert report.neo4j_write_called is False
    assert report.formal_graph_written is False


def test_test_graph_write_temp_workspace_if_available(tmp_path):
    if os.getenv("LIGHTRAG_ENABLE_REAL_DSL_TEST_GRAPH_WRITE") != "1":
        pytest.skip("Real LightRAG temp graph write is opt-in only.")

    from lightrag import LightRAG

    working_dir = tmp_path / "dsl_test_graph"
    rag = LightRAG(working_dir=str(working_dir))
    report = run_test_graph_write_dry_run(
        _build_fx_kg_payload(),
        lightrag_client=rag,
        config=_enabled_config(working_dir=str(working_dir), cleanup_after_run=True),
    )

    assert report.skipped is False
    assert report.cleanup_passed is True


def test_sidecar_written_with_graph_payload():
    store = KgMetadataSidecarStore()

    report = run_test_graph_write_dry_run(
        _build_fx_kg_payload(),
        lightrag_client=FakeLightRAG(),
        sidecar_store=store,
        config=_enabled_config(cleanup_after_run=False, rollback_after_run=False),
    )

    assert report.skipped is False
    assert report.sidecar_coverage_passed is True
    assert store.count() == report.sidecar_record_count
    assert report.full_sidecar_record_count == report.graph_insert_sidecar_record_count
    assert report.graph_insert_sidecar_alignment_status == "PASS"


def test_lc_graph_write_report_uses_graph_insert_sidecar_subset():
    store = KgMetadataSidecarStore()

    report = run_test_graph_write_dry_run(
        _build_lc_kg_payload(),
        lightrag_client=FakeLightRAG(),
        sidecar_store=store,
        config=_enabled_config(
            namespace="dsl_test_lc_graph",
            cleanup_after_run=False,
            rollback_after_run=False,
        ),
    )

    assert report.skipped is False
    assert report.full_sidecar_record_count == 847
    assert report.graph_insert_sidecar_record_count == 391
    assert report.sidecar_record_count == 391
    assert report.graph_insert_sidecar_alignment_status == "PASS"
    assert store.count() == 391


def test_report_serializable():
    report = run_test_graph_write_dry_run(
        _build_fx_kg_payload(),
        lightrag_client=FakeLightRAG(),
        config=_enabled_config(),
    )

    json.dumps(serialize_test_graph_write_report(report))


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


def _enabled_config(
    *,
    namespace: str = "dsl_test_fx_graph",
    cleanup_after_run: bool = True,
    rollback_after_run: bool = True,
    working_dir: str | None = None,
) -> TestGraphWriteConfig:
    return TestGraphWriteConfig(
        enabled=True,
        write_graph=True,
        namespace=namespace,
        cleanup_after_run=cleanup_after_run,
        rollback_after_run=rollback_after_run,
        working_dir=working_dir,
    )


def _payload_with_entity_status(status: str) -> DslKgPayload:
    payload = _build_fx_kg_payload()
    entity = payload.entities[0]
    metadata = {**entity.metadata, "knowledgeStatus": status}
    payload.entities[0] = replace(entity, metadata=metadata)
    return payload


def _payload_with_forbidden_relation() -> DslKgPayload:
    payload = _build_fx_kg_payload()
    relationship = payload.relationships[0]
    metadata = {**relationship.metadata, "relationType": "has_child"}
    payload.relationships[0] = replace(
        relationship,
        keywords="has_child",
        metadata=metadata,
    )
    return payload


def _custom_kg_object_count(custom_kg: dict[str, list[dict]]) -> int:
    return (
        len(custom_kg["chunks"])
        + len(custom_kg["entities"])
        + len(custom_kg["relationships"])
    )


def _custom_kg_external_keys(custom_kg: dict[str, list[dict]]) -> set[str]:
    keys = {
        chunk_external_key(item["source_id"])
        for item in custom_kg.get("chunks", [])
    }
    keys.update(
        entity_external_key(
            item["entity_type"],
            item["entity_name"],
            item["source_id"],
        )
        for item in custom_kg.get("entities", [])
    )
    keys.update(
        relationship_external_key(
            item["src_id"],
            item["tgt_id"],
            item["keywords"],
            item["source_id"],
        )
        for item in custom_kg.get("relationships", [])
    )
    return keys
