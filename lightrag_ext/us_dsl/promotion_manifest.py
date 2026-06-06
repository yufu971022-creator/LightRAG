from __future__ import annotations

from dataclasses import asdict
import hashlib
from typing import Any

from .promotion_types import (
    DECISION_APPROVED,
    DECISION_BLOCKED,
    DECISION_NEEDS_REVIEW,
    DECISION_REJECTED,
    PromotionDecision,
    PromotionManifest,
)


VALID_MANIFEST_DECISIONS = {
    DECISION_APPROVED,
    DECISION_REJECTED,
    DECISION_NEEDS_REVIEW,
    DECISION_BLOCKED,
}


def promotion_manifest_from_dict(data: dict[str, Any]) -> PromotionManifest:
    decisions = [
        promotion_decision_from_dict(item, manifest_id=str(data.get("manifest_id") or "manifest"))
        for item in data.get("decisions", [])
    ]
    return PromotionManifest(
        manifest_id=str(data.get("manifest_id") or _stable_hash("manifest", decisions)),
        module_name=str(data.get("module_name") or "unknown"),
        source_document=_string_or_none(data.get("source_document")),
        created_at=_string_or_none(data.get("created_at")),
        reviewer=_string_or_none(data.get("reviewer")),
        decisions=decisions,
        scope=dict(data.get("scope") or {}),
        notes=_string_or_none(data.get("notes")),
    )


def promotion_decision_from_dict(
    data: dict[str, Any],
    *,
    manifest_id: str = "manifest",
) -> PromotionDecision:
    candidate_id = str(data.get("candidate_id") or "")
    decision = str(data.get("decision") or DECISION_NEEDS_REVIEW)
    if decision not in VALID_MANIFEST_DECISIONS:
        decision = DECISION_NEEDS_REVIEW
    return PromotionDecision(
        promotion_id=str(data.get("promotion_id") or _stable_hash(manifest_id, candidate_id, decision)),
        candidate_id=candidate_id,
        decision=decision,
        reviewer=_string_or_none(data.get("reviewer")),
        reviewer_role=_string_or_none(data.get("reviewer_role")),
        decision_reason=str(data.get("decision_reason") or ""),
        decision_time=_string_or_none(data.get("decision_time")),
        evidence_checked=bool(data.get("evidence_checked")),
        version_checked=bool(data.get("version_checked")),
        term_checked=bool(data.get("term_checked")),
        comments=_string_or_none(data.get("comments")),
    )


def decision_blocks_formal_promotion(decision: PromotionDecision | None, metadata: dict[str, Any]) -> list[str]:
    if decision is None:
        return ["MISSING_MANIFEST_DECISION"]
    reasons: list[str] = []
    if decision.decision != DECISION_APPROVED:
        reasons.append(f"MANIFEST_DECISION_{decision.decision}")
    if not decision.reviewer:
        reasons.append("MISSING_REVIEWER")
    if not decision.evidence_checked:
        reasons.append("EVIDENCE_NOT_CHECKED")
    if _has_version_metadata(metadata) and not decision.version_checked:
        reasons.append("VERSION_NOT_CHECKED")
    if _has_term_metadata(metadata) and not decision.term_checked:
        reasons.append("TERM_NOT_CHECKED")
    return reasons


def decisions_by_candidate_id(manifest: PromotionManifest | None) -> dict[str, PromotionDecision]:
    if manifest is None:
        return {}
    return {item.candidate_id: item for item in manifest.decisions}


def serialize_promotion_manifest(manifest: PromotionManifest) -> dict[str, Any]:
    return asdict(manifest)


def _has_version_metadata(metadata: dict[str, Any]) -> bool:
    return any(
        metadata.get(key) not in (None, "", [])
        for key in ("ruleVersion", "latestFlag", "versionStatus", "supersedes", "versionGroupKey")
    )


def _has_term_metadata(metadata: dict[str, Any]) -> bool:
    return any(
        metadata.get(key) not in (None, "", [])
        for key in ("canonicalTerm", "originalTerm")
    )


def _stable_hash(*parts: Any) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _string_or_none(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


__all__ = [
    "VALID_MANIFEST_DECISIONS",
    "decision_blocks_formal_promotion",
    "decisions_by_candidate_id",
    "promotion_decision_from_dict",
    "promotion_manifest_from_dict",
    "serialize_promotion_manifest",
]
