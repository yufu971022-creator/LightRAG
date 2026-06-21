from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from .unified_e2e_types import to_plain_dict


@dataclass(frozen=True)
class ExecutionTraceEvent:
    event_id: str
    trace_id: str
    stage: str
    component: str
    operation: str
    input_ids: dict[str, str]
    output_ids: dict[str, str]
    status: str
    reason_code: str
    started_at: str
    completed_at: str
    elapsed_ms: float
    attempt_no: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


class UnifiedE2ETrace:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self.events: list[ExecutionTraceEvent] = []

    def record(
        self,
        *,
        stage: str,
        component: str,
        operation: str,
        input_ids: dict[str, str] | None = None,
        output_ids: dict[str, str] | None = None,
        status: str = "OK",
        reason_code: str = "OK",
        attempt_no: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionTraceEvent:
        start = datetime.now(UTC)
        begin = perf_counter()
        end = datetime.now(UTC)
        event = ExecutionTraceEvent(
            event_id=f"evt-{len(self.events) + 1:04d}",
            trace_id=self.trace_id,
            stage=stage,
            component=component,
            operation=operation,
            input_ids=input_ids or {},
            output_ids=output_ids or {},
            status=status,
            reason_code=reason_code,
            started_at=start.isoformat(),
            completed_at=end.isoformat(),
            elapsed_ms=round((perf_counter() - begin) * 1000, 3),
            attempt_no=attempt_no,
            metadata=metadata or {},
        )
        self.events.append(event)
        return event

    def to_list(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]
