from __future__ import annotations

from dataclasses import asdict

from lightrag_ext.us_dsl.ingestion_adapter import build_dsl_aware_ingestion_payload
from lightrag_ext.us_dsl.kg_metadata_sidecar import (
    KgMetadataSidecarRecord,
    KgMetadataSidecarStore,
    build_metadata_sidecar_records,
    validate_sidecar_coverage,
)
from lightrag_ext.us_dsl.kg_metadata_strategy import (
    STRATEGY_SIDECAR_ONLY,
    STRATEGY_SIDECAR_PLUS_MINIMAL_NATIVE,
    determine_metadata_strategy,
)
from lightrag_ext.us_dsl.kg_payload_mapper import build_dsl_kg_payload
from lightrag_ext.us_dsl.pilot_execution_pack import (
    build_minimal_pilot_dsl_result_from_us_blocks,
)
from lightrag_ext.us_dsl.source_text_unit_builder import detect_us_blocks
from lightrag_ext.us_dsl.tests.test_kg_payload_mapper import (
    LC_SOURCE,
    _build_fx_kg_payload,
    _load_lc_content,
)


def test_metadata_strategy_defaults_to_sidecar_when_native_not_supported():
    strategy = determine_metadata_strategy(native_custom_kg_supports_metadata=False)

    assert strategy.strategy_name == STRATEGY_SIDECAR_ONLY
    assert strategy.sidecar_required is True
    assert strategy.selected is True


def test_metadata_strategy_uses_sidecar_even_when_native_supported():
    strategy = determine_metadata_strategy(native_custom_kg_supports_metadata=True)

    assert strategy.strategy_name == STRATEGY_SIDECAR_PLUS_MINIMAL_NATIVE
    assert strategy.native_metadata_supported is True
    assert strategy.sidecar_required is True


def test_build_sidecar_records_fx():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")
    coverage = validate_sidecar_coverage(payload, records)

    assert len(records) == len(payload.chunks) + len(payload.entities) + len(
        payload.relationships
    )
    assert coverage.chunk_coverage_ratio == 1.0
    assert coverage.entity_coverage_ratio == 1.0
    assert coverage.relationship_coverage_ratio == 1.0
    assert coverage.pass_status == "PASS"


def test_build_sidecar_records_lc():
    payload = _build_lc_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_lc")
    coverage = validate_sidecar_coverage(payload, records)

    assert coverage.chunk_coverage_ratio == 1.0
    assert coverage.entity_coverage_ratio == 1.0
    assert coverage.relationship_coverage_ratio == 1.0
    assert coverage.pass_status == "PASS"


def test_sidecar_records_keep_evidence():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")

    for record in records:
        assert record.metadata.get("sourceUsId")
        assert record.metadata.get("textUnitId")
        assert record.metadata.get("sourceSpan")
        assert record.metadata.get("textHash")
        assert record.metadata.get("evidenceText")


def test_sidecar_records_keep_version_metadata():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")
    version_records = [
        record
        for record in records
        if record.metadata.get("ruleVersion") or record.metadata.get("supersedes")
    ]

    assert version_records
    assert any(record.metadata.get("ruleVersion") == "v2" for record in version_records)
    assert any(record.metadata.get("supersedes") == ["v1"] for record in version_records)


def test_sidecar_records_keep_review_status():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")

    for record in records:
        assert record.metadata.get("knowledgeStatus")
        assert record.metadata.get("validationStatus")
        assert record.metadata.get("reviewDecision")


def test_sidecar_id_stable():
    payload = _build_fx_kg_payload()
    first = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")
    second = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")

    assert {record.sidecar_id for record in first} == {
        record.sidecar_id for record in second
    }


def test_sidecar_store_idempotent_upsert():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")
    store = KgMetadataSidecarStore()

    store.upsert_records(records)
    store.upsert_records(records)

    assert store.count() == len(records)


def test_sidecar_namespace_delete():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")
    other_records = build_metadata_sidecar_records(payload, namespace="dsl_test_other")
    store = KgMetadataSidecarStore()
    store.upsert_records([*records, *other_records])

    deleted = store.delete_by_namespace("dsl_test_fx")

    assert deleted == len(records)
    assert store.count() == len(other_records)


def test_sidecar_json_export_import():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")
    store = KgMetadataSidecarStore()
    store.upsert_records(records)
    exported = store.export_json()
    imported = KgMetadataSidecarStore()

    imported.import_json(exported)

    assert imported.count() == store.count()


def test_sidecar_coverage_fails_when_metadata_missing():
    payload = _build_fx_kg_payload()
    records = build_metadata_sidecar_records(payload, namespace="dsl_test_fx")
    first = records[0]
    broken = asdict(first)
    broken["metadata"] = dict(broken["metadata"])
    broken["metadata"].pop("textHash", None)
    records[0] = KgMetadataSidecarRecord(**broken)
    coverage = validate_sidecar_coverage(payload, records)

    assert coverage.pass_status == "FAIL"
    assert coverage.evidence_missing_count >= 1


def _build_lc_kg_payload():
    content = _load_lc_content()
    blocks = detect_us_blocks(content)
    dsl_result = build_minimal_pilot_dsl_result_from_us_blocks(
        blocks,
        module_code="LCAB",
    )
    ingestion_payload = build_dsl_aware_ingestion_payload(
        content,
        document_id="DOC_LCAB_001",
        dsl_result=dsl_result,
        file_path=str(LC_SOURCE),
    )
    return build_dsl_kg_payload(ingestion_payload=ingestion_payload)
