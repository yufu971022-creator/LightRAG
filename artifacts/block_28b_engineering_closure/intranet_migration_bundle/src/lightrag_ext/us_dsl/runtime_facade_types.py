from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RuntimeOperation = Literal[
    "preflight",
    "ingest_documents",
    "query_function",
    "analyze_impact",
    "update_document_version",
    "delete_document_version",
    "delete_document",
    "rebuild_document_version",
    "health",
    "readiness",
    "diagnostics",
]


@dataclass(frozen=True)
class RuntimeRequest:
    operation: RuntimeOperation
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    run_id: str | None = None
    batch_id: str | None = None


@dataclass(frozen=True)
class RuntimeResult:
    operation: RuntimeOperation
    status: str
    trace_id: str
    run_id: str
    batch_id: str
    result: dict[str, Any]
    logs: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "status": self.status,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "batch_id": self.batch_id,
            "result": self.result,
            "logs": self.logs,
            "metrics": self.metrics,
            "reason_codes": self.reason_codes,
        }
