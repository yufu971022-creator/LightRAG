from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

REQUIRED_TRACE_FIELDS = [
    "timestamp",
    "level",
    "trace_id",
    "run_id",
    "batch_id",
    "document_id",
    "document_version_id",
    "query_id",
    "stage",
    "component",
    "event",
    "status",
    "reason_code",
    "elapsed_ms",
    "attempt_no",
]

_SENSITIVE_KEYS = {"api_key", "token", "secret", "authorization", "password", "prompt", "embedding", "model_response", "raw_text", "full_document"}


@dataclass
class StructuredRuntimeLogger:
    records: list[dict[str, Any]] = field(default_factory=list)

    def emit(
        self,
        *,
        trace_id: str,
        run_id: str,
        batch_id: str,
        stage: str,
        component: str,
        event: str,
        level: str = "INFO",
        status: str = "OK",
        reason_code: str = "",
        elapsed_ms: int = 0,
        attempt_no: int = 1,
        document_id: str = "",
        document_version_id: str = "",
        query_id: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "trace_id": trace_id,
            "run_id": run_id,
            "batch_id": batch_id,
            "document_id": document_id,
            "document_version_id": document_version_id,
            "query_id": query_id,
            "stage": stage,
            "component": component,
            "event": event,
            "status": status,
            "reason_code": reason_code,
            "elapsed_ms": elapsed_ms,
            "attempt_no": attempt_no,
        }
        if extra:
            record["extra"] = sanitize_log_payload(extra)
        self.records.append(record)
        return record

    def to_list(self) -> list[dict[str, Any]]:
        return list(self.records)


def sanitize_log_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(item in lowered for item in _SENSITIVE_KEYS):
            sanitized[str(key)] = "[redacted]"
        elif isinstance(value, str) and len(value) > 160:
            sanitized[str(key)] = f"[redacted_text len={len(value)}]"
        elif isinstance(value, list) and value and all(isinstance(item, (int, float)) for item in value):
            sanitized[str(key)] = f"[redacted_vector dim={len(value)}]"
        elif isinstance(value, dict):
            sanitized[str(key)] = sanitize_log_payload(value)
        else:
            sanitized[str(key)] = value
    return sanitized


def required_trace_fields_present(record: dict[str, Any]) -> bool:
    return all(field_name in record for field_name in REQUIRED_TRACE_FIELDS)


def logs_contain_forbidden_payload(records: list[dict[str, Any]]) -> dict[str, bool]:
    text = repr(records).lower()
    return {
        "logs_contain_full_document": "full raw document" in text or "complete source document" in text,
        "logs_contain_secret": "bearer " in text or "sk-" in text or "authorization:" in text,
    }
