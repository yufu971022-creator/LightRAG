from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

IssueType = Literal[
    "VERSION_REVIEW_REQUIRED",
    "VERSION_CONFLICT",
    "MISSING_EVIDENCE",
    "INVALID_TYPE",
    "INVALID_RELATION",
    "DANGLING_RELATIONSHIP",
    "TERM_AMBIGUITY",
    "REVIEW_REQUIRED",
    "INFO_ONLY",
]


@dataclass(frozen=True)
class IssueRecord:
    issue_id: str
    trace_id: str
    document_id: str
    document_version_id: str
    semantic_object_id: str
    object_kind: str
    issue_type: IssueType
    severity: str
    reason_code: str
    source_us_id: str | None
    text_unit_id: str | None
    source_span: dict[str, int]
    text_hash: str | None
    evidence_text: str
    domain_code: str | None
    feature_key: str | None
    version_group_key: str | None
    review_required: bool
    created_at: str
    confirmed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class IssueIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, IssueRecord] = {}
        self._load()

    def upsert_many(self, records: list[IssueRecord]) -> None:
        for record in records:
            if record.confirmed:
                raise ValueError("Issue records must not be confirmed in Block 24B-2")
            self._records[record.issue_id] = record
        self._flush()

    def all_records(self) -> list[IssueRecord]:
        return sorted(self._records.values(), key=lambda item: item.issue_id)

    def query_by_document(self, document_id: str) -> list[IssueRecord]:
        return [item for item in self.all_records() if item.document_id == document_id]

    def query_by_source_us(self, source_us_id: str) -> list[IssueRecord]:
        return [item for item in self.all_records() if item.source_us_id == source_us_id]

    def query_by_semantic_object(self, semantic_object_id: str) -> list[IssueRecord]:
        return [item for item in self.all_records() if item.semantic_object_id == semantic_object_id]

    def query_by_type(self, issue_type: IssueType) -> list[IssueRecord]:
        return [item for item in self.all_records() if item.issue_type == issue_type]

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for record in self.all_records():
            by_type[record.issue_type] = by_type.get(record.issue_type, 0) + 1
        return {
            "issue_record_count": len(self._records),
            "by_type": by_type,
            "confirmed_count": sum(1 for record in self._records.values() if record.confirmed),
        }

    def _load(self) -> None:
        if not self.path.exists():
            self._records = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self._records = {key: IssueRecord(**value) for key, value in raw.items()}

    def _flush(self) -> None:
        payload = {key: record.__dict__ for key, record in sorted(self._records.items())}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def make_issue_record(
    *,
    trace_id: str,
    document_id: str,
    document_version_id: str,
    semantic_object_id: str,
    object_kind: str,
    issue_type: IssueType,
    severity: str = "medium",
    reason_code: str,
    evidence_text: str,
    source_us_id: str | None = None,
    text_unit_id: str | None = None,
    source_span: dict[str, int] | None = None,
    text_hash: str | None = None,
    domain_code: str | None = None,
    feature_key: str | None = None,
    version_group_key: str | None = None,
    review_required: bool = True,
) -> IssueRecord:
    issue_id = _issue_id(document_id, document_version_id, semantic_object_id, issue_type, reason_code)
    return IssueRecord(
        issue_id=issue_id,
        trace_id=trace_id,
        document_id=document_id,
        document_version_id=document_version_id,
        semantic_object_id=semantic_object_id,
        object_kind=object_kind,
        issue_type=issue_type,
        severity=severity,
        reason_code=reason_code,
        source_us_id=source_us_id,
        text_unit_id=text_unit_id,
        source_span=source_span or {},
        text_hash=text_hash,
        evidence_text=evidence_text,
        domain_code=domain_code,
        feature_key=feature_key,
        version_group_key=version_group_key,
        review_required=review_required,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        confirmed=False,
    )


def _issue_id(document_id: str, document_version_id: str, semantic_object_id: str, issue_type: str, reason_code: str) -> str:
    raw = f"{document_id}:{document_version_id}:{semantic_object_id}:{issue_type}:{reason_code}"
    return "issue-" + hashlib.md5(raw.encode("utf-8")).hexdigest()
