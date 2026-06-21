from __future__ import annotations

from lightrag_ext.us_dsl.runtime_metrics import RuntimeMetrics, module_agnostic_metrics


def test_ingestion_metrics_are_emitted() -> None:
    metrics = RuntimeMetrics()
    metrics.record_ingestion(status="OK", route="DSL_FULL")
    assert "ingestion_documents_total{route=DSL_FULL,status=OK}" in metrics.snapshot()["counters"]


def test_query_metrics_are_emitted() -> None:
    metrics = RuntimeMetrics()
    metrics.record_query(status="QUALITY_GATE_PASSED", scenario="ONE_TO_MANY")
    assert "query_requests_total{scenario=ONE_TO_MANY,status=QUALITY_GATE_PASSED}" in metrics.snapshot()["counters"]


def test_quality_safety_metrics_are_emitted() -> None:
    metrics = RuntimeMetrics()
    metrics.record_quality_safety(status="OK", gate="citation")
    assert "quality_gate_checks_total{gate=citation,status=OK}" in metrics.snapshot()["counters"]


def test_metrics_are_module_agnostic() -> None:
    metrics = RuntimeMetrics()
    metrics.record_ingestion(status="OK", route="RAW_ONLY")
    assert module_agnostic_metrics(metrics.snapshot())
