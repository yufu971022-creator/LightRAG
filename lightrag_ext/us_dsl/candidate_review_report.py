from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .candidate_extraction import CandidateExtractionReport
from .candidate_review_policy import (
    CandidateReviewPolicy,
    detect_term_review_required,
    detect_version_review_required,
)
from .candidate_types import (
    CandidateEntity,
    CandidateRelation,
    KNOWLEDGE_STATUS_CANDIDATE,
    VALIDATION_INVALID_TYPE,
    VALIDATION_REVIEW_REQUIRED,
    VALIDATION_VALID,
)
from .ontology_auto_resolver import resolve_candidate_ontology


DECISION_AUTO_ACCEPT = "AUTO_ACCEPT_FOR_REPORT"
DECISION_AUTO_RESOLVE = "AUTO_RESOLVE"
DECISION_INFO_ONLY = "INFO_ONLY"
DECISION_REVIEW_REQUIRED = "REVIEW_REQUIRED"
DECISION_BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CandidateReviewDecision:
    candidate_id: str
    candidate_type: str
    decision: str
    reason_code: str
    reason: str
    human_review_required: bool
    review_priority: str
    risk_level: str
    confidence_score: float
    evidence_ready: bool
    version_review_required: bool
    term_review_required: bool
    ontology_review_required: bool
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str | None
    evidence_text: str | None
    suggested_action: str
    raw_candidate: dict[str, Any]


@dataclass
class CandidateReviewReport:
    report_id: str
    generated_at: str
    document_id: str | None
    total_candidates: int
    total_entities: int
    total_relations: int
    decision_distribution: dict[str, int]
    priority_distribution: dict[str, int]
    domain_distribution: dict[str, int]
    feature_distribution: dict[str, int]
    validation_distribution: dict[str, int]
    review_required_count: int
    human_review_required_count: int
    human_review_ratio: float
    version_review_required_count: int
    term_review_required_count: int
    ontology_review_required_count: int
    blocked_count: int
    auto_accept_count: int
    auto_resolve_count: int
    info_only_count: int
    review_required_items: list[CandidateReviewDecision]
    auto_items_summary: list[dict[str, Any]]
    blocked_items: list[CandidateReviewDecision]
    grouped_by_feature: dict[str, dict[str, int]]
    grouped_by_domain: dict[str, dict[str, int]]
    recommendations: list[str]
    risks: list[str]
    next_step: str


def build_candidate_review_decisions(
    candidates: list[CandidateEntity | CandidateRelation],
    *,
    version_context: dict | None = None,
    synonym_context: dict | None = None,
    policy: CandidateReviewPolicy | None = None,
) -> list[CandidateReviewDecision]:
    policy = policy or CandidateReviewPolicy()
    return [
        _review_decision(
            candidate,
            version_context=version_context,
            synonym_context=synonym_context,
            policy=policy,
        )
        for candidate in candidates
    ]


def build_candidate_review_report(
    candidates: list[CandidateEntity | CandidateRelation],
    *,
    document_id: str | None = None,
    version_context: dict | None = None,
    synonym_context: dict | None = None,
    policy: CandidateReviewPolicy | None = None,
) -> CandidateReviewReport:
    policy = policy or CandidateReviewPolicy()
    decisions = build_candidate_review_decisions(
        candidates,
        version_context=version_context,
        synonym_context=synonym_context,
        policy=policy,
    )
    total = len(decisions)
    human_count = sum(1 for item in decisions if item.human_review_required)
    human_ratio = human_count / total if total else 0.0
    risks: list[str] = []
    if human_ratio > policy.warn_human_review_ratio:
        risks.append("Review burden too high; adjust auto-resolve policy before pilot.")

    review_required_items = [
        item for item in decisions if item.decision == DECISION_REVIEW_REQUIRED
    ]
    blocked_items = [item for item in decisions if item.decision == DECISION_BLOCKED]
    auto_items_summary = [
        {
            "candidate_id": item.candidate_id,
            "candidate_type": item.candidate_type,
            "decision": item.decision,
            "reason_code": item.reason_code,
            "feature_key": item.feature_key,
            "domain_code": item.domain_code,
        }
        for item in decisions
        if not item.human_review_required
    ]
    decision_counts = Counter(item.decision for item in decisions)
    report = CandidateReviewReport(
        report_id=_report_id(document_id),
        generated_at=datetime.now(UTC).isoformat(),
        document_id=document_id,
        total_candidates=total,
        total_entities=sum(1 for candidate in candidates if isinstance(candidate, CandidateEntity)),
        total_relations=sum(1 for candidate in candidates if isinstance(candidate, CandidateRelation)),
        decision_distribution=dict(decision_counts),
        priority_distribution=dict(Counter(item.review_priority for item in decisions)),
        domain_distribution=dict(Counter(item.domain_code or "unknown" for item in decisions)),
        feature_distribution=dict(Counter(item.feature_key or "unknown" for item in decisions)),
        validation_distribution=dict(
            Counter(candidate.validation_status for candidate in candidates)
        ),
        review_required_count=decision_counts.get(DECISION_REVIEW_REQUIRED, 0),
        human_review_required_count=human_count,
        human_review_ratio=human_ratio,
        version_review_required_count=sum(
            1 for item in decisions if item.version_review_required
        ),
        term_review_required_count=sum(1 for item in decisions if item.term_review_required),
        ontology_review_required_count=sum(
            1 for item in decisions if item.ontology_review_required
        ),
        blocked_count=decision_counts.get(DECISION_BLOCKED, 0),
        auto_accept_count=decision_counts.get(DECISION_AUTO_ACCEPT, 0),
        auto_resolve_count=decision_counts.get(DECISION_AUTO_RESOLVE, 0),
        info_only_count=decision_counts.get(DECISION_INFO_ONLY, 0),
        review_required_items=review_required_items,
        auto_items_summary=auto_items_summary,
        blocked_items=blocked_items,
        grouped_by_feature=_grouped(decisions, key_name="feature_key"),
        grouped_by_domain=_grouped(decisions, key_name="domain_code"),
        recommendations=_recommendations(decisions, human_ratio, policy),
        risks=risks,
        next_step="",
    )
    report.next_step = _next_step(report, policy)
    return report


def build_candidate_review_report_from_candidate_extraction_report(
    extraction_report: CandidateExtractionReport,
    *,
    version_context: dict | None = None,
    synonym_context: dict | None = None,
    policy: CandidateReviewPolicy | None = None,
) -> CandidateReviewReport:
    return build_candidate_review_report(
        [*extraction_report.candidate_entities, *extraction_report.candidate_relations],
        document_id=extraction_report.document_id,
        version_context=version_context,
        synonym_context=synonym_context,
        policy=policy,
    )


def serialize_candidate_review_report(report: CandidateReviewReport) -> dict[str, Any]:
    return {
        "reportId": report.report_id,
        "generatedAt": report.generated_at,
        "documentId": report.document_id,
        "totalCandidates": report.total_candidates,
        "totalEntities": report.total_entities,
        "totalRelations": report.total_relations,
        "decisionDistribution": report.decision_distribution,
        "priorityDistribution": report.priority_distribution,
        "domainDistribution": report.domain_distribution,
        "featureDistribution": report.feature_distribution,
        "validationDistribution": report.validation_distribution,
        "reviewRequiredCount": report.review_required_count,
        "humanReviewRequiredCount": report.human_review_required_count,
        "humanReviewRatio": report.human_review_ratio,
        "versionReviewRequiredCount": report.version_review_required_count,
        "termReviewRequiredCount": report.term_review_required_count,
        "ontologyReviewRequiredCount": report.ontology_review_required_count,
        "blockedCount": report.blocked_count,
        "autoAcceptCount": report.auto_accept_count,
        "autoResolveCount": report.auto_resolve_count,
        "infoOnlyCount": report.info_only_count,
        "reviewRequiredItems": [asdict(item) for item in report.review_required_items],
        "autoItemsSummary": report.auto_items_summary,
        "blockedItems": [asdict(item) for item in report.blocked_items],
        "groupedByFeature": report.grouped_by_feature,
        "groupedByDomain": report.grouped_by_domain,
        "recommendations": report.recommendations,
        "risks": report.risks,
        "nextStep": report.next_step,
    }


def _review_decision(
    candidate: CandidateEntity | CandidateRelation,
    *,
    version_context: dict | None,
    synonym_context: dict | None,
    policy: CandidateReviewPolicy,
) -> CandidateReviewDecision:
    version_required, version_reason = (
        detect_version_review_required(candidate, version_context)
        if policy.review_version_conflict
        else (False, "")
    )
    term_required, term_reason = (
        detect_term_review_required(candidate, synonym_context)
        if policy.review_term_ambiguity
        else (False, "")
    )
    evidence_ready = _evidence_ready(candidate)
    ontology_required = _ontology_review_required(candidate, policy)
    high_risk_low_confidence = _high_risk_low_confidence(candidate, policy)

    if candidate.knowledge_status != KNOWLEDGE_STATUS_CANDIDATE:
        return _decision(
            candidate,
            decision=DECISION_BLOCKED,
            reason_code="NON_CANDIDATE_STATUS",
            reason="Only Candidate knowledge_status is allowed in review report.",
            priority="P0",
            risk="HIGH",
            version_required=version_required,
            term_required=term_required,
            ontology_required=True,
            evidence_ready=evidence_ready,
            suggested_action="Do not promote. Fix status before any downstream use.",
        )
    if version_required:
        return _decision(
            candidate,
            decision=DECISION_REVIEW_REQUIRED,
            reason_code="VERSION_REVIEW_REQUIRED",
            reason=version_reason,
            priority="P0",
            risk="HIGH",
            version_required=True,
            term_required=term_required,
            ontology_required=ontology_required,
            evidence_ready=evidence_ready,
            suggested_action="Review only the version/latest-rule conflict.",
        )
    if term_required:
        return _decision(
            candidate,
            decision=DECISION_REVIEW_REQUIRED,
            reason_code="TERM_REVIEW_REQUIRED",
            reason=term_reason,
            priority="P1",
            risk="MEDIUM",
            version_required=False,
            term_required=True,
            ontology_required=ontology_required,
            evidence_ready=evidence_ready,
            suggested_action="Resolve the ambiguous term mapping.",
        )
    if policy.review_missing_evidence and not evidence_ready:
        return _decision(
            candidate,
            decision=DECISION_REVIEW_REQUIRED,
            reason_code="MISSING_EVIDENCE",
            reason="Candidate lacks required source evidence.",
            priority="P1",
            risk="HIGH",
            version_required=False,
            term_required=False,
            ontology_required=ontology_required,
            evidence_ready=False,
            suggested_action="Bind evidence before any promotion discussion.",
        )
    if ontology_required:
        resolve_result = resolve_candidate_ontology(
            candidate,
            allowed_entity_types=_allowed_entity_types(candidate),
            allowed_relation_types=_allowed_relation_types(candidate),
            domain_code=candidate.domain_code,
            section_type=candidate.section_type,
            feature_key=candidate.feature_key,
            evidence_text=candidate.evidence_text,
            known_objects=_known_objects(candidate),
        )
        if resolve_result.safe_to_auto_resolve:
            decision = (
                DECISION_INFO_ONLY
                if resolve_result.reason_code == "CONTEXT_MISMATCH_INFO_ONLY"
                else DECISION_AUTO_RESOLVE
            )
            suggested = (
                "Keep as informational candidate; no manual review required."
                if decision == DECISION_INFO_ONLY
                else "Auto-resolved by deterministic ontology rule. No manual review required."
            )
            return _decision(
                candidate,
                decision=decision,
                reason_code=resolve_result.reason_code,
                reason=resolve_result.reason,
                priority="P3",
                risk="LOW",
                version_required=False,
                term_required=False,
                ontology_required=False,
                evidence_ready=evidence_ready,
                suggested_action=suggested,
            )
    if ontology_required:
        return _decision(
            candidate,
            decision=DECISION_REVIEW_REQUIRED,
            reason_code="ONTOLOGY_REVIEW_REQUIRED",
            reason="Candidate type or relation type is not safely mapped to ontology.",
            priority="P1",
            risk="MEDIUM",
            version_required=False,
            term_required=False,
            ontology_required=True,
            evidence_ready=evidence_ready,
            suggested_action="Review ontology mapping only; do not promote automatically.",
        )
    if high_risk_low_confidence:
        return _decision(
            candidate,
            decision=DECISION_REVIEW_REQUIRED,
            reason_code="HIGH_RISK_LOW_CONFIDENCE",
            reason="High-risk domain or section has low candidate confidence.",
            priority="P2",
            risk="MEDIUM",
            version_required=False,
            term_required=False,
            ontology_required=False,
            evidence_ready=evidence_ready,
            suggested_action="Review the low-confidence high-risk candidate.",
        )
    if _auto_resolved(candidate):
        return _decision(
            candidate,
            decision=DECISION_AUTO_RESOLVE,
            reason_code="AUTO_RESOLVED",
            reason="Candidate was resolved by deterministic rule.",
            priority="P3",
            risk="LOW",
            version_required=False,
            term_required=False,
            ontology_required=False,
            evidence_ready=evidence_ready,
            suggested_action="Auto-resolved by deterministic rule. No manual review required.",
        )
    if (
        candidate.validation_status == VALIDATION_VALID
        and candidate.confidence_score >= policy.auto_accept_confidence_threshold
        and evidence_ready
    ):
        return _decision(
            candidate,
            decision=DECISION_AUTO_ACCEPT,
            reason_code="VALID_HIGH_CONFIDENCE",
            reason="Valid high-confidence candidate with evidence.",
            priority="P3",
            risk="LOW",
            version_required=False,
            term_required=False,
            ontology_required=False,
            evidence_ready=True,
            suggested_action="Keep as candidate context. No manual review required.",
        )
    return _decision(
        candidate,
        decision=DECISION_INFO_ONLY,
        reason_code="LOW_RISK_INFO_ONLY",
        reason="Low-risk candidate can remain in the report without manual review.",
        priority="P3",
        risk="LOW",
        version_required=False,
        term_required=False,
        ontology_required=False,
        evidence_ready=evidence_ready,
        suggested_action="Keep as informational candidate. No manual review required.",
    )


def _decision(
    candidate: CandidateEntity | CandidateRelation,
    *,
    decision: str,
    reason_code: str,
    reason: str,
    priority: str,
    risk: str,
    version_required: bool,
    term_required: bool,
    ontology_required: bool,
    evidence_ready: bool,
    suggested_action: str,
) -> CandidateReviewDecision:
    return CandidateReviewDecision(
        candidate_id=candidate.candidate_id,
        candidate_type="entity" if isinstance(candidate, CandidateEntity) else "relation",
        decision=decision,
        reason_code=reason_code,
        reason=reason,
        human_review_required=decision in {DECISION_REVIEW_REQUIRED, DECISION_BLOCKED},
        review_priority=priority,
        risk_level=risk,
        confidence_score=candidate.confidence_score,
        evidence_ready=evidence_ready,
        version_review_required=version_required,
        term_review_required=term_required,
        ontology_review_required=ontology_required,
        source_us_id=candidate.source_us_id,
        feature_key=candidate.feature_key,
        domain_code=candidate.domain_code,
        section_type=candidate.section_type,
        evidence_text=candidate.evidence_text,
        suggested_action=suggested_action,
        raw_candidate=asdict(candidate),
    )


def _evidence_ready(candidate: CandidateEntity | CandidateRelation) -> bool:
    return bool(candidate.source_text_unit_id and candidate.text_hash and candidate.evidence_text)


def _ontology_review_required(
    candidate: CandidateEntity | CandidateRelation,
    policy: CandidateReviewPolicy,
) -> bool:
    if not policy.review_invalid_type:
        return False
    if candidate.validation_status == VALIDATION_INVALID_TYPE:
        return True
    if candidate.validation_status == VALIDATION_REVIEW_REQUIRED:
        if isinstance(candidate, CandidateEntity) and candidate.entity_type == "CandidateEntity":
            return False
        if (
            isinstance(candidate, CandidateRelation)
            and candidate.relation_type == "CandidateRelation"
        ):
            return False
        return True
    return False


def _high_risk_low_confidence(
    candidate: CandidateEntity | CandidateRelation,
    policy: CandidateReviewPolicy,
) -> bool:
    high_risk = (
        candidate.domain_code in policy.high_risk_domains
        or candidate.section_type in policy.high_risk_sections
    )
    return high_risk and candidate.confidence_score < policy.low_confidence_threshold


def _auto_resolved(candidate: CandidateEntity | CandidateRelation) -> bool:
    return bool(candidate.raw.get("autoResolved") or candidate.raw.get("auto_resolved"))


def _allowed_entity_types(candidate: CandidateEntity | CandidateRelation) -> list[str]:
    values = candidate.raw.get("allowedEntityTypes") or candidate.raw.get("allowed_entity_types")
    if isinstance(values, list):
        return [str(item) for item in values if isinstance(item, str)]
    if (
        isinstance(candidate, CandidateEntity)
        and candidate.entity_type
        and candidate.validation_status == VALIDATION_VALID
    ):
        return [candidate.entity_type]
    return []


def _allowed_relation_types(candidate: CandidateEntity | CandidateRelation) -> list[str]:
    values = candidate.raw.get("allowedRelationTypes") or candidate.raw.get("allowed_relation_types")
    if isinstance(values, list):
        return [str(item) for item in values if isinstance(item, str)]
    if (
        isinstance(candidate, CandidateRelation)
        and candidate.relation_type
        and candidate.validation_status == VALIDATION_VALID
    ):
        return [candidate.relation_type]
    return []


def _known_objects(candidate: CandidateEntity | CandidateRelation) -> list[dict[str, Any]]:
    values = candidate.raw.get("knownObjects") or candidate.raw.get("known_objects")
    if isinstance(values, list):
        return [dict(item) for item in values if isinstance(item, dict)]
    return []


def _grouped(
    decisions: list[CandidateReviewDecision],
    *,
    key_name: str,
) -> dict[str, dict[str, int]]:
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for item in decisions:
        key = getattr(item, key_name) or "unknown"
        groups[key][item.decision] += 1
    return {key: dict(counter) for key, counter in groups.items()}


def _recommendations(
    decisions: list[CandidateReviewDecision],
    human_ratio: float,
    policy: CandidateReviewPolicy,
) -> list[str]:
    recommendations = [
        "Do not promote candidates automatically.",
        "Use auto-accepted candidates as report context only.",
    ]
    if any(item.version_review_required for item in decisions):
        recommendations.append("Review version/latest-rule conflicts first.")
    if any(item.term_review_required for item in decisions):
        recommendations.append("Resolve term ambiguity before pilot usage.")
    if human_ratio > policy.warn_human_review_ratio:
        recommendations.append("Reduce review burden before pilot.")
    return recommendations


def _next_step(
    report: CandidateReviewReport,
    policy: CandidateReviewPolicy,
) -> str:
    if report.blocked_count > 0:
        return "FIX_BLOCKED_CANDIDATES"
    if report.version_review_required_count > 0:
        return "REVIEW_VERSION_CONFLICTS_ONLY"
    if report.human_review_ratio > policy.warn_human_review_ratio:
        return "REDUCE_REVIEW_BURDEN_BEFORE_PILOT"
    if report.human_review_required_count > 0:
        return "REVIEW_REQUIRED_ITEMS_ONLY"
    return "READY_FOR_PILOT_REPORT_ONLY"


def _report_id(document_id: str | None) -> str:
    import hashlib

    raw = f"{document_id or 'candidate-review'}|{datetime.now(UTC).isoformat()}"
    return f"review-{hashlib.md5(raw.encode('utf-8')).hexdigest()[:12]}"


__all__ = [
    "CandidateReviewDecision",
    "CandidateReviewReport",
    "build_candidate_review_decisions",
    "build_candidate_review_report",
    "build_candidate_review_report_from_candidate_extraction_report",
    "serialize_candidate_review_report",
]
