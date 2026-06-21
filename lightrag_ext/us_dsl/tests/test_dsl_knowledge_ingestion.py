from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

from lightrag_ext.us_dsl.dsl_knowledge_ingestion import (
    DslKnowledgeIngestionConfig,
    run_dsl_knowledge_ingestion,
    serialize_dsl_knowledge_ingestion_report,
)
from lightrag_ext.us_dsl.dsl_knowledge_ingestion_policy import (
    prepare_policy_approved_ingestion_payload,
)
from lightrag_ext.us_dsl.dsl_knowledge_ingestion_writer import WriteResult
from lightrag_ext.us_dsl.tests.test_dsl_knowledge_ingestion_readiness import (
    _unsafe_payload,
)


def test_ingestion_disabled_skips():
    report = run_dsl_knowledge_ingestion(
        config=DslKnowledgeIngestionConfig(
            enabled=False,
            ingest_mode="readiness",
            namespace="dsl_test_disabled",
        )
    )

    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False


def test_canary_ingestion_requires_readiness():
    report = run_dsl_knowledge_ingestion(
        config=DslKnowledgeIngestionConfig(
            enabled=True,
            ingest_mode="canary",
            namespace="production",
            module_name="LCAB",
        )
    )

    assert report.stage == "canary"
    assert report.skipped is True
    assert report.skip_reason == "READINESS_GATE_FAILED"
    assert report.ainsert_custom_kg_called is False


def test_canary_ingestion_writes_test_graph_if_enabled():
    report = run_dsl_knowledge_ingestion(config=_lc_config("canary", "dsl_test_ingest_canary"))

    assert report.stage == "canary"
    assert report.ainsert_custom_kg_called is True
    assert report.graph_write_succeeded is True
    assert report.failed_batch_count == 0
    assert report.cleanup_passed is True
    assert report.rollback_passed is True
    assert report.neo4j_connected is False
    assert report.production_write is False
    assert report.recommended_next_step == "RUN_MODULE_LEVEL_TEST_GRAPH_INGESTION"


def test_canary_subset_limits():
    report = run_dsl_knowledge_ingestion(config=_lc_config("canary", "dsl_test_ingest_limits"))

    assert report.custom_kg_chunk_count <= 20
    assert report.custom_kg_entity_count <= 50
    assert report.custom_kg_relationship_count <= 50


def test_canary_subset_no_unsafe_objects():
    prepared = prepare_policy_approved_ingestion_payload(
        _unsafe_payload(),
        namespace="dsl_test_canary_no_unsafe",
    )
    text = json.dumps(prepared.custom_kg_input)

    assert "ReviewRequired" not in text
    assert "InfoOnly" not in text
    assert "VersionReviewRequired" not in text
    assert "MissingEvidence" not in text
    assert "InvalidRelation" not in text


def test_canary_subset_no_forbidden_relations():
    prepared = prepare_policy_approved_ingestion_payload(
        _unsafe_payload(),
        namespace="dsl_test_canary_no_forbidden",
    )
    forbidden = {"has_child", "belongs_to", "references_to", "queries_from", "contains"}

    assert not [
        item
        for item in prepared.custom_kg_input["relationships"]
        if str(item.get("keywords")).lower() in forbidden
    ]


def test_canary_endpoint_closure():
    report = run_dsl_knowledge_ingestion(config=_lc_config("canary", "dsl_test_ingest_endpoint"))

    assert report.endpoint_closure_passed is True
    assert report.dangling_relationship_count == 0


def test_canary_sidecar_alignment():
    report = run_dsl_knowledge_ingestion(config=_lc_config("canary", "dsl_test_ingest_sidecar"))

    assert report.sidecar_alignment_passed is True
    assert report.sidecar_record_count == (
        report.custom_kg_chunk_count
        + report.custom_kg_entity_count
        + report.custom_kg_relationship_count
    )


def test_canary_ingestion_rollback_cleanup():
    report = run_dsl_knowledge_ingestion(config=_lc_config("canary", "dsl_test_ingest_cleanup"))

    assert report.graph_write_succeeded is True
    assert report.rollback_passed is True
    assert report.cleanup_passed is True


def test_canary_ingestion_failed_write_stops(monkeypatch):
    def fake_writer(custom_kg_batches, *, config):
        return WriteResult(
            enabled=True,
            skipped=False,
            skip_reason="BATCH_WRITE_FAILED",
            working_dir="/tmp/lightrag_dsl_ingestion_dsl_test_failed",
            namespace=config.namespace,
            batch_count=len(custom_kg_batches),
            failed_batch_count=1,
            ainsert_custom_kg_called=True,
            graph_write_attempted=True,
            graph_write_succeeded=False,
            neo4j_connected=False,
            production_write=False,
            formal_graph_written=False,
            cleanup_passed=True,
            rollback_passed=True,
            elapsed_ms=1,
            batches=[],
            issues=[{"severity": "ERROR", "code": "BATCH_WRITE_FAILED"}],
            recommended_next_step="FIX_CANARY_GRAPH_WRITE",
        )

    monkeypatch.setattr(
        "lightrag_ext.us_dsl.dsl_knowledge_ingestion.write_custom_kg_batches_to_lightrag",
        fake_writer,
    )

    report = run_dsl_knowledge_ingestion(config=_lc_config("canary", "dsl_test_ingest_failed"))

    assert report.stage == "canary"
    assert report.failed_batch_count > 0
    assert report.recommended_next_step == "FIX_CANARY_GRAPH_WRITE"


def test_canary_no_module_level_execution(monkeypatch):
    called = {"module": False}

    def fake_module(canary_report, *, config):
        called["module"] = True
        return canary_report

    monkeypatch.setattr(
        "lightrag_ext.us_dsl.dsl_knowledge_ingestion.run_module_level_dsl_knowledge_ingestion",
        fake_module,
    )

    report = run_dsl_knowledge_ingestion(config=_lc_config("canary", "dsl_test_ingest_no_module"))

    assert report.stage == "canary"
    assert called["module"] is False


def test_canary_ingestion_no_lc_hardcode():
    forbidden_terms = [
        "LCAB",
        "Acceptable Bank",
        "Bank Status",
        "Swift Code",
        "Transfer To",
        "Bank Default Confirmation",
        "eflowNum",
        "Suggested Rating",
        "FX",
    ]
    generic_files = [
        "lightrag_ext/us_dsl/dsl_knowledge_ingestion.py",
        "lightrag_ext/us_dsl/dsl_knowledge_ingestion_writer.py",
        "lightrag_ext/us_dsl/dsl_knowledge_ingestion_policy.py",
        "lightrag_ext/us_dsl/dsl_knowledge_ingestion_readiness.py",
    ]

    found = {
        path: [term for term in forbidden_terms if term in Path(path).read_text()]
        for path in generic_files
    }
    assert not {path: terms for path, terms in found.items() if terms}


def test_report_serializable():
    report = run_dsl_knowledge_ingestion(
        config=_lc_config(
            "readiness",
            "dsl_test_ingest_serializable",
        )
    )

    json.dumps(serialize_dsl_knowledge_ingestion_report(report))


def test_canary_report_serializable():
    report = run_dsl_knowledge_ingestion(
        config=_lc_config(
            "canary",
            "dsl_test_ingest_canary_serializable",
        )
    )

    json.dumps(serialize_dsl_knowledge_ingestion_report(report))


def test_module_level_ingestion_requires_readiness():
    report = run_dsl_knowledge_ingestion(
        config=DslKnowledgeIngestionConfig(
            enabled=True,
            ingest_mode="module",
            namespace="production",
            module_name="LCAB",
        )
    )

    assert report.stage == "module"
    assert report.skipped is True
    assert report.skip_reason == "READINESS_GATE_FAILED"
    assert report.ainsert_custom_kg_called is False
    assert report.recommended_next_step == "FIX_READINESS_GATE"


def test_module_level_ingestion_requires_canary(monkeypatch):
    def failed_canary(readiness_report, *, config, source_path=None, dsl_payload=None, module_name=None):
        return replace(
            readiness_report,
            stage="canary",
            graph_write_succeeded=False,
            rollback_passed=False,
            cleanup_passed=False,
            failed_batch_count=1,
            ainsert_custom_kg_called=False,
        )

    monkeypatch.setattr(
        "lightrag_ext.us_dsl.dsl_knowledge_ingestion.run_canary_dsl_knowledge_ingestion",
        failed_canary,
    )

    report = run_dsl_knowledge_ingestion(
        config=_lc_config(
            "module",
            "dsl_test_module_requires_canary",
            cleanup_after_run=True,
            rollback_after_run=True,
        )
    )

    assert report.stage == "module"
    assert report.skipped is True
    assert report.ainsert_custom_kg_called is False
    assert report.canary_prerequisite_passed is False
    assert report.recommended_next_step == "RUN_CANARY_TEST_GRAPH_INGESTION"


def test_module_level_subset_limits():
    report = run_dsl_knowledge_ingestion(
        config=_module_test_config("dsl_test_module_limits", cleanup=True)
    )

    assert report.stage == "module"
    assert report.custom_kg_chunk_count <= report.approved_chunk_count
    assert report.custom_kg_chunk_count <= 2000
    assert report.custom_kg_entity_count <= 5000
    assert report.custom_kg_relationship_count <= 5000


def test_module_level_no_unsafe_objects():
    prepared = prepare_policy_approved_ingestion_payload(
        _unsafe_payload(),
        namespace="dsl_test_module_no_unsafe",
    )
    text = json.dumps(prepared.custom_kg_input)

    assert "ReviewRequired" not in text
    assert "InfoOnly" not in text
    assert "VersionReviewRequired" not in text
    assert "MissingEvidence" not in text
    assert "InvalidRelation" not in text


def test_module_level_no_forbidden_relations():
    prepared = prepare_policy_approved_ingestion_payload(
        _unsafe_payload(),
        namespace="dsl_test_module_no_forbidden",
    )
    forbidden = {"has_child", "belongs_to", "references_to", "queries_from", "contains"}

    assert not [
        item
        for item in prepared.custom_kg_input["relationships"]
        if str(item.get("keywords")).lower() in forbidden
    ]


def test_module_level_endpoint_closure():
    report = run_dsl_knowledge_ingestion(
        config=_module_test_config("dsl_test_module_endpoint", cleanup=True)
    )

    assert report.endpoint_closure_passed is True
    assert report.dangling_relationship_count == 0


def test_module_level_sidecar_alignment():
    report = run_dsl_knowledge_ingestion(
        config=_module_test_config("dsl_test_module_sidecar", cleanup=True)
    )

    assert report.sidecar_alignment_passed is True
    assert report.sidecar_record_count == (
        report.custom_kg_chunk_count
        + report.custom_kg_entity_count
        + report.custom_kg_relationship_count
    )


def test_module_level_batching():
    report = run_dsl_knowledge_ingestion(
        config=_module_test_config(
            "dsl_test_module_batching",
            batch_size=5,
            cleanup=True,
        )
    )

    assert report.batch_count > 1
    assert report.failed_batch_count == 0


def test_module_level_ingestion_writes_test_graph_if_enabled():
    report = run_dsl_knowledge_ingestion(
        config=_module_test_config("dsl_test_module_write", cleanup=True)
    )

    assert report.stage == "module"
    assert report.canary_prerequisite_passed is True
    assert report.ainsert_custom_kg_called is True
    assert report.graph_write_succeeded is True
    assert report.failed_batch_count == 0
    assert report.neo4j_connected is False
    assert report.production_write is False
    assert report.recommended_next_step == "RUN_ACTUAL_EFFECT_TESTS_ON_TEST_GRAPH"


def test_module_level_keep_working_dir_by_default():
    report = run_dsl_knowledge_ingestion(
        config=_module_test_config("dsl_test_module_keep_dir", cleanup=False)
    )
    try:
        assert report.stage == "module"
        assert report.graph_write_succeeded is True
        assert report.cleanup_after_run is False
        assert report.rollback_after_run is False
        assert report.cleanup_passed is False
        assert report.working_dir
        assert Path(report.working_dir).exists()
        assert report.how_to_cleanup
    finally:
        if report.working_dir:
            shutil.rmtree(report.working_dir, ignore_errors=True)


def test_module_level_cleanup_optional():
    report = run_dsl_knowledge_ingestion(
        config=_module_test_config("dsl_test_module_cleanup", cleanup=True)
    )

    assert report.cleanup_after_run is True
    assert report.rollback_after_run is True
    assert report.cleanup_passed is True
    assert report.rollback_passed is True


def test_module_level_failed_write_stops_batches(monkeypatch):
    def fake_writer(custom_kg_batches, *, config):
        if config.ingest_mode == "canary":
            return WriteResult(
                enabled=True,
                skipped=False,
                skip_reason=None,
                working_dir="/tmp/lightrag_dsl_ingestion_dsl_test_module_fake_canary",
                namespace=config.namespace,
                batch_count=len(custom_kg_batches),
                failed_batch_count=0,
                ainsert_custom_kg_called=True,
                graph_write_attempted=True,
                graph_write_succeeded=True,
                neo4j_connected=False,
                production_write=False,
                formal_graph_written=False,
                cleanup_passed=True,
                rollback_passed=True,
                elapsed_ms=1,
                batches=[],
                issues=[],
                recommended_next_step="RUN_MODULE_LEVEL_TEST_GRAPH_INGESTION",
            )
        return WriteResult(
            enabled=True,
            skipped=False,
            skip_reason="BATCH_WRITE_FAILED",
            working_dir="/tmp/lightrag_dsl_ingestion_dsl_test_module_failed",
            namespace=config.namespace,
            batch_count=len(custom_kg_batches),
            failed_batch_count=1,
            ainsert_custom_kg_called=True,
            graph_write_attempted=True,
            graph_write_succeeded=False,
            neo4j_connected=False,
            production_write=False,
            formal_graph_written=False,
            cleanup_passed=True,
            rollback_passed=True,
            elapsed_ms=1,
            batches=[],
            issues=[{"severity": "ERROR", "code": "BATCH_WRITE_FAILED"}],
            recommended_next_step="FIX_MODULE_GRAPH_WRITE",
        )

    monkeypatch.setattr(
        "lightrag_ext.us_dsl.dsl_knowledge_ingestion.write_custom_kg_batches_to_lightrag",
        fake_writer,
    )

    report = run_dsl_knowledge_ingestion(
        config=_module_test_config("dsl_test_module_failed", cleanup=True)
    )

    assert report.stage == "module"
    assert report.failed_batch_count > 0
    assert report.recommended_next_step == "FIX_MODULE_GRAPH_WRITE"


def test_module_level_no_lc_hardcode():
    forbidden_terms = [
        "LCAB",
        "Acceptable Bank",
        "Bank Status",
        "Swift Code",
        "Transfer To",
        "Bank Default Confirmation",
        "eflowNum",
        "Suggested Rating",
        "FX",
    ]
    generic_files = [
        "lightrag_ext/us_dsl/dsl_knowledge_ingestion.py",
        "lightrag_ext/us_dsl/dsl_knowledge_ingestion_writer.py",
        "lightrag_ext/us_dsl/dsl_knowledge_ingestion_policy.py",
    ]

    found = {
        path: [term for term in forbidden_terms if term in Path(path).read_text()]
        for path in generic_files
    }
    assert not {path: terms for path, terms in found.items() if terms}


def test_module_level_report_serializable():
    report = run_dsl_knowledge_ingestion(
        config=_module_test_config("dsl_test_module_serializable", cleanup=True)
    )

    json.dumps(serialize_dsl_knowledge_ingestion_report(report))


def test_no_lightrag_core_modified():
    disallowed_prefixes = (
        "lightrag/lightrag.py",
        "lightrag/operate.py",
        "lightrag/prompt.py",
        "lightrag/api/",
    )
    root = Path.cwd()
    changed = [
        path
        for path in _git_diff_names(root)
        if path.startswith(disallowed_prefixes)
    ]

    assert changed == []


def test_no_unsafe_objects_written():
    report = run_dsl_knowledge_ingestion(
        config=_lc_config(
            "readiness",
            "dsl_test_ingest_no_unsafe",
        )
    )

    assert report.sidecar_alignment_passed is True
    assert report.endpoint_closure_passed is True
    assert report.forbidden_relation_count == 0
    assert report.dangling_relationship_count >= 0


def _lc_config(
    mode: str,
    namespace: str,
    *,
    batch_size: int = 20,
    cleanup_after_run: bool = False,
    rollback_after_run: bool = False,
) -> DslKnowledgeIngestionConfig:
    return DslKnowledgeIngestionConfig(
        enabled=True,
        ingest_mode=mode,
        namespace=namespace,
        module_name="LCAB",
        max_chunks=20,
        max_entities=50,
        max_relationships=50,
        module_max_chunks=20,
        module_max_entities=50,
        module_max_relationships=50,
        batch_size=batch_size,
        cleanup_after_run=cleanup_after_run,
        rollback_after_run=rollback_after_run,
    )


def _module_test_config(
    namespace: str,
    *,
    batch_size: int = 100,
    cleanup: bool,
) -> DslKnowledgeIngestionConfig:
    return _lc_config(
        "module",
        namespace,
        batch_size=batch_size,
        cleanup_after_run=cleanup,
        rollback_after_run=cleanup,
    )


def _git_diff_names(root: Path) -> list[str]:
    import subprocess

    result = subprocess.run(
        ["git", "diff", "--name-only", "--", "lightrag"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
