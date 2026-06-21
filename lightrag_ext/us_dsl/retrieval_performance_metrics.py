from __future__ import annotations

from .multi_module_eval_types import LatencyStats, MultiModulePolicy, PerformanceMetrics, latency_stats


def build_performance_metrics(
    *,
    ingestion_time_ms: float,
    measured_query_runs_ms: list[float],
    warmup_latency_ms: float | None,
    embedding_call_count: int,
    llm_call_count: int,
    storage_size_bytes: int,
    parse_time_ms: float = 0.0,
    embedding_time_ms: float = 0.0,
    llm_extraction_time_ms: float = 0.0,
    graph_write_time_ms: float = 0.0,
    sidecar_write_time_ms: float = 0.0,
) -> PerformanceMetrics:
    return PerformanceMetrics(
        ingestion_time_ms=ingestion_time_ms,
        query_latency=latency_stats(measured_query_runs_ms, warmup_latency_ms),
        embedding_call_count=embedding_call_count,
        llm_call_count=llm_call_count,
        storage_size_bytes=storage_size_bytes,
        parse_time_ms=parse_time_ms,
        embedding_time_ms=embedding_time_ms,
        llm_extraction_time_ms=llm_extraction_time_ms,
        graph_write_time_ms=graph_write_time_ms,
        sidecar_write_time_ms=sidecar_write_time_ms,
    )


def latency_report_has_required_stats(stats: LatencyStats) -> bool:
    return stats.measured_run_count >= 5 and stats.warmup_excluded and stats.max_ms >= stats.p95_ms >= stats.median_ms >= stats.min_ms


def performance_ratios(
    baseline: PerformanceMetrics,
    candidate: PerformanceMetrics,
) -> dict[str, float]:
    return {
        "ingestion_time_ratio": _safe_ratio(candidate.ingestion_time_ms, baseline.ingestion_time_ms),
        "query_p95_latency_ratio": _safe_ratio(candidate.query_latency.p95_ms, baseline.query_latency.p95_ms),
        "storage_size_ratio": _safe_ratio(candidate.storage_size_bytes, baseline.storage_size_bytes),
    }


def performance_passes_policy(
    baseline: PerformanceMetrics,
    candidate: PerformanceMetrics,
    policy: MultiModulePolicy,
) -> bool:
    ratios = performance_ratios(baseline, candidate)
    return (
        ratios["ingestion_time_ratio"] <= policy.max_ingestion_time_ratio
        and ratios["query_p95_latency_ratio"] <= policy.max_query_p95_latency_ratio
    )


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0 if numerator == 0 else float("inf")
    return float(numerator) / float(denominator)
