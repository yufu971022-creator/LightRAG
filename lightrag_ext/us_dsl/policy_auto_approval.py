from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from .promotion_manifest import promotion_manifest_from_dict
from .promotion_policy import has_complete_evidence
from .promotion_types import (
    DECISION_APPROVED,
    ELIGIBLE,
    OBJECT_KIND_VERSION_RELATION,
    PromotionCandidate,
    PromotionManifest,
)


@dataclass(frozen=True)
class PolicyAutoApprovalConfig:
    enabled: bool = True
    target_graph_type: str = "test_graph"
    namespace: str = "dsl_test_e2e_graph"
    allow_formal_graph: bool = False
    allow_production: bool = False
    allow_review_required: bool = False
    allow_info_only: bool = False
    allow_version_review_required: bool = False
    allow_missing_evidence: bool = False
    allow_invalid_relation: bool = False
    allow_forbidden_relation: bool = False
    require_evidence: bool = True
    require_source_span_or_text_hash: bool = True
    require_valid_relation_endpoint: bool = True
    require_sidecar_alignment: bool = True


@dataclass(frozen=True)
class PolicyAutoApprovalDecision:
    object_id: str
    object_kind: str
    approved_for_test_graph: bool
    approved_for_formal_graph: bool = False
    reason_code: str = ""
    reason: str = ""
    blocking_reasons: list[str] = field(default_factory=list)
    evidence_complete: bool = False
    version_safe: bool = False
    relation_safe: bool = False
    sidecar_ready: bool = False
    idempotency_key: str | None = None


@dataclass(frozen=True)
class PolicyAutoApprovalResult:
    decisions: list[PolicyAutoApprovalDecision]
    approved_candidates: list[PromotionCandidate]
    blocked_candidates: list[PromotionCandidate]
    approved_for_test_graph_count: int
    blocked_from_graph_count: int
    block_reason_distribution: dict[str, int]
    version_safe_for_test_count: int
    version_still_review_required_count: int
    version_formal_blocked_count: int
    manifest: PromotionManifest


def run_policy_auto_approval(
    candidates: list[PromotionCandidate],
    *,
    config: PolicyAutoApprovalConfig | None = None,
    manifest_id: str = "POLICY-AUTO-APPROVAL-TEST",
    module_name: str = "module",
    source_document: str | None = None,
) -> PolicyAutoApprovalResult:
    config = config or PolicyAutoApprovalConfig()
    decisions = [
        evaluate_policy_auto_approval(candidate, config=config)
        for candidate in candidates
    ]
    approved_ids = {
        decision.object_id
        for decision in decisions
        if decision.approved_for_test_graph
    }
    approved = [candidate for candidate in candidates if candidate.candidate_id in approved_ids]
    blocked = [candidate for candidate in candidates if candidate.candidate_id not in approved_ids]
    manifest = _manifest_from_approved(
        approved,
        manifest_id=manifest_id,
        module_name=module_name,
        source_document=source_document,
    )
    reason_counts = Counter(
        reason
        for decision in decisions
        if not decision.approved_for_test_graph
        for reason in decision.blocking_reasons
    )
    return PolicyAutoApprovalResult(
        decisions=decisions,
        approved_candidates=approved,
        blocked_candidates=blocked,
        approved_for_test_graph_count=len(approved),
        blocked_from_graph_count=len(blocked),
        block_reason_distribution=dict(reason_counts),
        version_safe_for_test_count=sum(
            1
            for candidate in approved
            if _is_version_candidate(candidate)
        ),
        version_still_review_required_count=sum(
            1
            for candidate in blocked
            if _is_version_candidate(candidate)
            and any("VERSION" in reason for reason in candidate.blocking_reasons)
        ),
        version_formal_blocked_count=sum(
            1
            for candidate in candidates
            if _is_version_candidate(candidate)
        ),
        manifest=manifest,
    )


def evaluate_policy_auto_approval(
    candidate: PromotionCandidate,
    *,
    config: PolicyAutoApprovalConfig | None = None,
) -> PolicyAutoApprovalDecision:
    config = config or PolicyAutoApprovalConfig()
    blocking_reasons = list(candidate.blocking_reasons)
    evidence_complete = has_complete_evidence(candidate.evidence)
    if config.require_evidence and not evidence_complete:
        blocking_reasons.append("MISSING_EVIDENCE")
    if config.require_source_span_or_text_hash and not (
        candidate.evidence.get("sourceSpan") or candidate.evidence.get("textHash")
    ):
        blocking_reasons.append("MISSING_SOURCE_SPAN_OR_TEXT_HASH")
    if not config.allow_review_required and _has_token(candidate, "ReviewRequired", "REVIEW_REQUIRED"):
        blocking_reasons.append("REVIEW_REQUIRED_BLOCKED")
    if not config.allow_info_only and _has_token(candidate, "InfoOnly", "INFO_ONLY"):
        blocking_reasons.append("INFO_ONLY_BLOCKED")
    if not config.allow_version_review_required and _has_token(
        candidate,
        "VersionReviewRequired",
        "VERSION_REVIEW",
    ):
        blocking_reasons.append("VERSION_REVIEW_REQUIRED_BLOCKED")
    if not config.allow_missing_evidence and _has_token(
        candidate,
        "MissingEvidence",
        "MISSING_EVIDENCE",
    ):
        blocking_reasons.append("MISSING_EVIDENCE")
    if not config.allow_invalid_relation and _has_token(
        candidate,
        "InvalidRelation",
        "INVALID_RELATION",
    ):
        blocking_reasons.append("INVALID_RELATION_BLOCKED")
    if not config.allow_invalid_relation and "INVALID_RELATION" in blocking_reasons:
        blocking_reasons.append("INVALID_RELATION_BLOCKED")
    if not config.allow_forbidden_relation and "FORBIDDEN_RELATION_TYPE" in blocking_reasons:
        blocking_reasons.append("FORBIDDEN_RELATION_BLOCKED")
    relation_safe = not any(
        reason in blocking_reasons
        for reason in (
            "INVALID_RELATION",
            "INVALID_RELATION_TYPE",
            "FORBIDDEN_RELATION_TYPE",
            "INVALID_RELATION_BLOCKED",
            "FORBIDDEN_RELATION_BLOCKED",
            "RELATION_ENDPOINT_NOT_ELIGIBLE",
        )
    )
    version_safe = not any("VERSION" in reason for reason in blocking_reasons)
    sidecar_ready = bool(candidate.audit_metadata.get("sidecarId"))
    if config.require_sidecar_alignment and not sidecar_ready:
        blocking_reasons.append("SIDECAR_NOT_READY")
    approved = (
        config.enabled
        and config.target_graph_type == "test_graph"
        and config.allow_formal_graph is False
        and config.allow_production is False
        and candidate.eligibility_status == ELIGIBLE
        and not blocking_reasons
        and evidence_complete
        and relation_safe
        and sidecar_ready
    )
    return PolicyAutoApprovalDecision(
        object_id=candidate.candidate_id,
        object_kind=candidate.object_kind,
        approved_for_test_graph=approved,
        approved_for_formal_graph=False,
        reason_code="POLICY_APPROVED_FOR_TEST_GRAPH" if approved else "POLICY_BLOCKED",
        reason=(
            "Policy-approved for test graph only."
            if approved
            else "Candidate blocked by test graph policy."
        ),
        blocking_reasons=_dedupe(blocking_reasons),
        evidence_complete=evidence_complete,
        version_safe=version_safe,
        relation_safe=relation_safe,
        sidecar_ready=sidecar_ready,
        idempotency_key=candidate.idempotency_key,
    )


def serialize_policy_auto_approval_result(result: PolicyAutoApprovalResult) -> dict[str, Any]:
    return {
        "decisions": [asdict(item) for item in result.decisions],
        "approved_for_test_graph_count": result.approved_for_test_graph_count,
        "blocked_from_graph_count": result.blocked_from_graph_count,
        "block_reason_distribution": result.block_reason_distribution,
        "version_safe_for_test_count": result.version_safe_for_test_count,
        "version_still_review_required_count": result.version_still_review_required_count,
        "version_formal_blocked_count": result.version_formal_blocked_count,
        "manifest": asdict(result.manifest),
    }


def _manifest_from_approved(
    approved: list[PromotionCandidate],
    *,
    manifest_id: str,
    module_name: str,
    source_document: str | None,
) -> PromotionManifest:
    return promotion_manifest_from_dict(
        {
            "manifest_id": manifest_id,
            "module_name": module_name,
            "source_document": source_document,
            "reviewer": "POLICY_AUTO_APPROVAL_TEST_ONLY",
            "notes": "Policy auto-approval for test graph only; not business confirmation.",
            "decisions": [
                {
                    "candidate_id": candidate.candidate_id,
                    "decision": DECISION_APPROVED,
                    "reviewer": "POLICY_AUTO_APPROVAL_TEST_ONLY",
                    "reviewer_role": "TEST_POLICY",
                    "decision_reason": "Policy-approved for test graph only.",
                    "evidence_checked": True,
                    "version_checked": True,
                    "term_checked": True,
                }
                for candidate in approved
            ],
        }
    )


def _has_token(candidate: PromotionCandidate, *tokens: str) -> bool:
    metadata = dict(candidate.source_object.get("metadata") or {})
    values = {
        str(candidate.knowledge_status or ""),
        str(candidate.review_decision or ""),
        str(candidate.validation_status or ""),
        str(candidate.proposed_relation_type or ""),
        str(metadata.get("knowledgeStatus") or ""),
        str(metadata.get("reviewDecision") or ""),
        str(metadata.get("validationStatus") or ""),
        str(metadata.get("reasonCode") or ""),
        str(metadata.get("relationType") or ""),
    }
    return any(token in values for token in tokens)


def _is_version_candidate(candidate: PromotionCandidate) -> bool:
    return (
        candidate.object_kind == OBJECT_KIND_VERSION_RELATION
        or candidate.proposed_entity_type == "RuleVersion"
        or str(candidate.proposed_relation_type or "").startswith("Version")
        or candidate.proposed_relation_type == "HasVersion"
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


__all__ = [
    "PolicyAutoApprovalConfig",
    "PolicyAutoApprovalDecision",
    "PolicyAutoApprovalResult",
    "evaluate_policy_auto_approval",
    "run_policy_auto_approval",
    "serialize_policy_auto_approval_result",
]
