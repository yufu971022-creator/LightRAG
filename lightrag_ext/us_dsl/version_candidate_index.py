from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .version_retrieval_types import VersionCandidate

CURRENT_VISIBLE_DOCUMENT_STATES = {None, "ACTIVE", "CURRENT", "PROCESSED", "READY"}
DELETED_DOCUMENT_STATES = {"DELETED", "TOMBSTONED", "INVALID"}


class VersionCandidateIndex:
    def __init__(self, candidates: list[VersionCandidate] | None = None) -> None:
        self._candidates = list(candidates or [])

    @classmethod
    def from_candidates(cls, candidates: list[VersionCandidate]) -> "VersionCandidateIndex":
        return cls(candidates)

    @classmethod
    def from_sqlite(cls, path: str | Path) -> "VersionCandidateIndex":
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM version_candidates").fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()
        return cls([_candidate_from_row(dict(row)) for row in rows])

    def all_candidates(self) -> list[VersionCandidate]:
        return sorted(self._candidates, key=_stable_key)

    def query_by_semantic_object_id(self, semantic_object_id: str) -> list[VersionCandidate]:
        return [item for item in self.all_candidates() if item.semantic_object_id == semantic_object_id]

    def query_by_version_group_key(self, version_group_key: str, *, include_deleted: bool = False) -> list[VersionCandidate]:
        return [item for item in self.all_candidates() if item.version_group_key == version_group_key and (include_deleted or not _is_deleted(item))]

    def query_by_canonical_identity(self, stable_identity_key: str) -> list[VersionCandidate]:
        return [item for item in self.all_candidates() if item.stable_identity_key == stable_identity_key]

    def query_by_document_version_id(self, document_version_id: str) -> list[VersionCandidate]:
        return [item for item in self.all_candidates() if item.document_version_id == document_version_id]

    def query_by_as_of_time(self, version_group_key: str, as_of_time: str, *, include_deleted: bool = False) -> list[VersionCandidate]:
        return [
            item
            for item in self.query_by_version_group_key(version_group_key, include_deleted=include_deleted)
            if _valid_at(item, as_of_time)
        ]

    def query_by_version_status(self, version_status: str) -> list[VersionCandidate]:
        target = _normalize_status(version_status)
        return [item for item in self.all_candidates() if _normalize_status(item.version_status) == target]

    def current_search_candidates(self, version_group_key: str) -> list[VersionCandidate]:
        return [
            item
            for item in self.query_by_version_group_key(version_group_key)
            if item.active_contribution and item.document_version_status in CURRENT_VISIBLE_DOCUMENT_STATES
        ]

    def history_search_candidates(self, version_group_key: str) -> list[VersionCandidate]:
        return self.query_by_version_group_key(version_group_key, include_deleted=True)

    def snapshot(self) -> dict[str, Any]:
        by_group: dict[str, int] = {}
        for item in self._candidates:
            by_group[item.version_group_key] = by_group.get(item.version_group_key, 0) + 1
        return {
            "candidate_count": len(self._candidates),
            "by_version_group": by_group,
            "active_current_candidate_count": sum(1 for item in self._candidates if item.active_contribution and not _is_deleted(item)),
            "deleted_projection_count": sum(1 for item in self._candidates if _is_deleted(item)),
        }


def _valid_at(item: VersionCandidate, as_of_time: str) -> bool:
    if not item.valid_from:
        return False
    if item.valid_from > as_of_time:
        return False
    return item.valid_to is None or as_of_time < item.valid_to


def _is_deleted(item: VersionCandidate) -> bool:
    return item.document_version_status in DELETED_DOCUMENT_STATES


def _normalize_status(value: str | None) -> str:
    return str(value or "UNKNOWN").upper()


def _stable_key(item: VersionCandidate) -> tuple[str, str, str]:
    return (item.stable_identity_key or item.semantic_object_id, item.version_member_id, item.document_version_id)


def _candidate_from_row(row: dict[str, Any]) -> VersionCandidate:
    return VersionCandidate(
        semantic_object_id=row["semantic_object_id"],
        semantic_relation_id=row.get("semantic_relation_id"),
        version_group_key=row["version_group_key"],
        version_member_id=row["version_member_id"],
        rule_version=row.get("rule_version"),
        version_status=row.get("version_status"),
        latest_flag=_bool_or_none(row.get("latest_flag")),
        valid_from=row.get("valid_from"),
        valid_to=row.get("valid_to"),
        supersedes_member_id=row.get("supersedes_member_id"),
        document_id=row["document_id"],
        document_version_id=row["document_version_id"],
        document_version_status=row.get("document_version_status"),
        source_us_id=row.get("source_us_id"),
        text_unit_id=row.get("text_unit_id"),
        source_span=json.loads(row.get("source_span_json") or "{}"),
        text_hash=row.get("text_hash"),
        evidence_excerpt=row.get("evidence_excerpt"),
        knowledge_status=row.get("knowledge_status"),
        review_decision=row.get("review_decision"),
        issue_types=json.loads(row.get("issue_types_json") or "[]"),
        active_contribution=bool(row.get("active_contribution", 1)),
        semantic_relevance_score=float(row.get("semantic_relevance_score") or 0.0),
        evidence_quality_score=float(row.get("evidence_quality_score") or 0.0),
        stable_identity_key=row.get("stable_identity_key"),
    )


def _bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return bool(int(value))
