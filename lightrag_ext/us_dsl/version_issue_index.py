from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .version_retrieval_types import VersionIssueRecord

VERSION_ISSUE_TYPES = {
    "VERSION_REVIEW_REQUIRED",
    "VERSION_CONFLICT",
    "MULTIPLE_CURRENT",
    "MULTIPLE_LATEST",
    "MISSING_VERSION_EVIDENCE",
    "SUPERSEDES_TARGET_MISSING",
    "SUPERSEDES_CYCLE",
    "SUPERSEDES_CHAIN_AMBIGUOUS",
    "DOCUMENT_VERSION_CONFLICT",
    "VALID_TIME_OVERLAP",
}


class VersionIssueIndex:
    def __init__(self, issues: list[VersionIssueRecord] | None = None) -> None:
        self._issues: dict[str, VersionIssueRecord] = {}
        self.upsert_many(list(issues or []))

    @classmethod
    def from_issues(cls, issues: list[VersionIssueRecord]) -> "VersionIssueIndex":
        return cls(issues)

    @classmethod
    def from_sqlite(cls, path: str | Path) -> "VersionIssueIndex":
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM version_issues").fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()
        return cls([_issue_from_row(dict(row)) for row in rows])

    def upsert_many(self, issues: list[VersionIssueRecord]) -> None:
        for issue in issues:
            if issue.issue_type not in VERSION_ISSUE_TYPES:
                raise ValueError(f"Unsupported version issue type: {issue.issue_type}")
            self._issues[issue.issue_id] = issue

    def all_issues(self) -> list[VersionIssueRecord]:
        return sorted(self._issues.values(), key=lambda item: item.issue_id)

    def query_by_version_group_key(self, version_group_key: str) -> list[VersionIssueRecord]:
        return [item for item in self.all_issues() if item.version_group_key == version_group_key]

    def query_by_semantic_object_id(self, semantic_object_id: str) -> list[VersionIssueRecord]:
        return [item for item in self.all_issues() if item.semantic_object_id == semantic_object_id]

    def query_by_type(self, issue_type: str) -> list[VersionIssueRecord]:
        return [item for item in self.all_issues() if item.issue_type == issue_type]

    def snapshot(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for issue in self.all_issues():
            by_type[issue.issue_type] = by_type.get(issue.issue_type, 0) + 1
        return {
            "issue_record_count": len(self._issues),
            "by_type": by_type,
            "pfss_fact_count": 0,
            "idempotency_key_count": len(set(self._issues)),
        }


def make_version_issue(
    *,
    version_group_key: str,
    issue_type: str,
    reason_code: str,
    severity: str = "medium",
    semantic_object_id: str | None = None,
    semantic_relation_id: str | None = None,
    member_ids: list[str] | None = None,
    document_version_ids: list[str] | None = None,
    source_us_ids: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    review_required: bool = True,
    issue_status: str = "OPEN",
) -> VersionIssueRecord:
    member_ids = sorted(set(member_ids or []))
    document_version_ids = sorted(set(document_version_ids or []))
    source_us_ids = sorted(set(source_us_ids or []))
    evidence_refs = sorted(set(evidence_refs or []))
    raw = ":".join([version_group_key, issue_type, reason_code, "|".join(member_ids), "|".join(document_version_ids)])
    return VersionIssueRecord(
        issue_id="version-issue-" + hashlib.md5(raw.encode("utf-8")).hexdigest(),
        version_group_key=version_group_key,
        semantic_object_id=semantic_object_id,
        semantic_relation_id=semantic_relation_id,
        issue_type=issue_type,
        severity=severity,
        reason_code=reason_code,
        member_ids=member_ids,
        document_version_ids=document_version_ids,
        source_us_ids=source_us_ids,
        evidence_refs=evidence_refs,
        review_required=review_required,
        issue_status=issue_status,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


def _issue_from_row(row: dict[str, Any]) -> VersionIssueRecord:
    return VersionIssueRecord(
        issue_id=row["issue_id"],
        version_group_key=row["version_group_key"],
        semantic_object_id=row.get("semantic_object_id"),
        semantic_relation_id=row.get("semantic_relation_id"),
        issue_type=row["issue_type"],
        severity=row.get("severity") or "medium",
        reason_code=row.get("reason_code") or row["issue_type"],
        member_ids=json.loads(row.get("member_ids_json") or "[]"),
        document_version_ids=json.loads(row.get("document_version_ids_json") or "[]"),
        source_us_ids=json.loads(row.get("source_us_ids_json") or "[]"),
        evidence_refs=json.loads(row.get("evidence_refs_json") or "[]"),
        review_required=bool(row.get("review_required", 1)),
        issue_status=row.get("issue_status") or "OPEN",
        created_at=row.get("created_at") or "",
    )
