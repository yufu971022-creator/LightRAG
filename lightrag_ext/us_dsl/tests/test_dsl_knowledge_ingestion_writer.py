from __future__ import annotations

from lightrag_ext.us_dsl.dsl_knowledge_ingestion import split_custom_kg_batches
from lightrag_ext.us_dsl.dsl_knowledge_ingestion_policy import (
    prepare_policy_approved_ingestion_payload,
)
from lightrag_ext.us_dsl.dsl_knowledge_ingestion_types import DslKnowledgeIngestionConfig
from lightrag_ext.us_dsl.dsl_knowledge_ingestion_writer import (
    write_custom_kg_batches_to_lightrag,
)
from lightrag_ext.us_dsl.kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship


def test_ingestion_disabled_skips():
    prepared = prepare_policy_approved_ingestion_payload(
        _valid_payload(),
        namespace="dsl_test_writer_disabled",
    )
    batches = split_custom_kg_batches(prepared.custom_kg_input, batch_size=20)

    result = write_custom_kg_batches_to_lightrag(
        batches,
        config=DslKnowledgeIngestionConfig(
            enabled=False,
            namespace="dsl_test_writer_disabled",
        ),
    )

    assert result.skipped is True
    assert result.ainsert_custom_kg_called is False


def test_canary_ingestion_writes_test_graph_if_enabled():
    prepared = prepare_policy_approved_ingestion_payload(
        _valid_payload(),
        namespace="dsl_test_writer_canary",
    )
    batches = split_custom_kg_batches(prepared.custom_kg_input, batch_size=20)

    result = write_custom_kg_batches_to_lightrag(
        batches,
        config=DslKnowledgeIngestionConfig(
            enabled=True,
            namespace="dsl_test_writer_canary",
            cleanup_after_run=True,
            rollback_after_run=True,
        ),
    )

    assert result.ainsert_custom_kg_called is True
    assert result.graph_write_succeeded is True
    assert result.failed_batch_count == 0
    assert result.cleanup_passed is True
    assert result.rollback_passed is True


def test_canary_ingestion_no_neo4j_no_production():
    prepared = prepare_policy_approved_ingestion_payload(
        _valid_payload(),
        namespace="dsl_test_writer_safe",
    )
    batches = split_custom_kg_batches(prepared.custom_kg_input, batch_size=20)

    result = write_custom_kg_batches_to_lightrag(
        batches,
        config=DslKnowledgeIngestionConfig(
            enabled=True,
            namespace="dsl_test_writer_safe",
            cleanup_after_run=True,
            rollback_after_run=True,
        ),
    )

    assert result.neo4j_connected is False
    assert result.production_write is False
    assert result.formal_graph_written is False


def test_module_level_ingestion_batches():
    prepared = prepare_policy_approved_ingestion_payload(
        _valid_payload(),
        namespace="dsl_test_writer_batches",
    )

    batches = split_custom_kg_batches(prepared.custom_kg_input, batch_size=1)

    assert len(batches) >= 1
    assert all(batch["chunks"] for batch in batches)


def _valid_payload() -> DslKgPayload:
    metadata = {
        "documentId": "TEST-DOC",
        "sourceUsId": "US-TEST-001",
        "textUnitId": "tu-1",
        "sourceSpan": {"start": 0, "end": 20},
        "textHash": "hash-test",
        "evidenceText": "Test feature has field Alpha.",
        "featureKey": "TestFeature",
        "domainCode": "MasterData",
        "sectionType": "field_table",
        "knowledgeStatus": "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": "AUTO_ACCEPT_FOR_REPORT",
        "confidenceScore": 1.0,
        "ruleVersion": "v1",
        "latestFlag": True,
        "versionStatus": "Current",
        "supersedes": [],
    }
    return DslKgPayload(
        chunks=[
            KgChunk(
                content="Test feature has field Alpha.",
                source_id="tu-1",
                metadata={**metadata, "validationStatus": "CHUNK", "reviewDecision": "CHUNK"},
            )
        ],
        entities=[
            KgEntity(
                entity_name="Test Feature",
                entity_type="FeatureCatalog",
                description="Test feature.",
                source_id="tu-1",
                metadata={**metadata, "candidateId": "entity-feature"},
            ),
            KgEntity(
                entity_name="Alpha",
                entity_type="FieldSpec",
                description="Alpha is a field.",
                source_id="tu-1",
                metadata={**metadata, "candidateId": "entity-alpha"},
            ),
        ],
        relationships=[
            KgRelationship(
                src_id="Test Feature",
                tgt_id="Alpha",
                description="Test feature has field Alpha.",
                keywords="HasFieldSpec",
                source_id="tu-1",
                metadata={**metadata, "candidateId": "relation-alpha", "relationType": "HasFieldSpec"},
            )
        ],
        metadata={"moduleName": "TEST", "source": "test-source"},
    )
