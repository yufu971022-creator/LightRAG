from __future__ import annotations

from lightrag_ext.us_dsl.multi_module_eval_types import MultiModulePolicy
from lightrag_ext.us_dsl.retrieval_performance_metrics import (
    build_performance_metrics,
    latency_report_has_required_stats,
    performance_passes_policy,
    performance_ratios,
)


def _perf(ingestion: float = 100.0, runs: list[float] | None = None):
    return build_performance_metrics(
        ingestion_time_ms=ingestion,
        measured_query_runs_ms=runs or [10, 11, 12, 13, 14],
        warmup_latency_ms=20,
        embedding_call_count=3,
        llm_call_count=1,
        storage_size_bytes=1000,
        parse_time_ms=10,
        embedding_time_ms=20,
        llm_extraction_time_ms=30,
        graph_write_time_ms=40,
        sidecar_write_time_ms=0,
    )


def test_latency_reports_median_and_p95() -> None:
    metrics = _perf()
    assert metrics.query_latency.median_ms == 12
    assert metrics.query_latency.p95_ms >= metrics.query_latency.median_ms


def test_warmup_is_excluded() -> None:
    metrics = _perf()
    assert metrics.query_latency.warmup_excluded is True
    assert metrics.query_latency.max_ms == 14


def test_five_measured_runs_are_required() -> None:
    assert latency_report_has_required_stats(_perf().query_latency) is True
    assert latency_report_has_required_stats(_perf(runs=[1, 2]).query_latency) is False


def test_ingestion_and_query_costs_are_separate() -> None:
    metrics = _perf()
    assert metrics.ingestion_time_ms == 100
    assert metrics.query_latency.median_ms == 12


def test_embedding_and_llm_call_counts_are_reported() -> None:
    metrics = _perf()
    assert metrics.embedding_call_count == 3
    assert metrics.llm_call_count == 1


def test_performance_thresholds_come_from_manifest() -> None:
    policy = MultiModulePolicy(max_ingestion_time_ratio=2.0, max_query_p95_latency_ratio=2.0)
    baseline = _perf(ingestion=100, runs=[10, 10, 10, 10, 10])
    candidate = _perf(ingestion=150, runs=[12, 12, 12, 12, 12])
    assert performance_passes_policy(baseline, candidate, policy) is True
    assert performance_ratios(baseline, candidate)["ingestion_time_ratio"] == 1.5
