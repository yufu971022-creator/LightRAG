from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeMetrics:
    counters: dict[str, int] = field(default_factory=dict)
    gauges: dict[str, float] = field(default_factory=dict)
    samples: list[dict[str, Any]] = field(default_factory=list)

    def increment(self, name: str, amount: int = 1, **labels: str) -> None:
        key = _metric_key(name, labels)
        self.counters[key] = self.counters.get(key, 0) + amount

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        self.gauges[_metric_key(name, labels)] = value

    def observe(self, name: str, value: float, **labels: str) -> None:
        self.samples.append({"name": name, "value": value, "labels": dict(labels)})

    def record_ingestion(self, *, status: str, route: str, count: int = 1) -> None:
        self.increment("ingestion_documents_total", count, status=status, route=route)

    def record_query(self, *, status: str, scenario: str) -> None:
        self.increment("query_requests_total", 1, status=status, scenario=scenario)

    def record_quality_safety(self, *, status: str, gate: str) -> None:
        self.increment("quality_gate_checks_total", 1, status=status, gate=gate)

    def snapshot(self) -> dict[str, Any]:
        return {"counters": dict(sorted(self.counters.items())), "gauges": dict(sorted(self.gauges.items())), "samples": list(self.samples)}


def _metric_key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    suffix = ",".join(f"{key}={labels[key]}" for key in sorted(labels))
    return f"{name}{{{suffix}}}"


def module_agnostic_metrics(snapshot: dict[str, Any]) -> bool:
    text = repr(snapshot).lower()
    return "module_code" not in text and "module_name" not in text
