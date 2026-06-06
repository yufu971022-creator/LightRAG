from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from .promotion_types import (
    TARGET_FORMAL_GRAPH,
    ConfirmedGraphObject,
    ConfirmedGraphWritePlan,
)


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


@dataclass(frozen=True)
class GraphWriteGovernanceReport:
    pass_status: str
    production_write_blocked: bool
    missing_manifest_count: int
    missing_evidence_count: int
    version_uncertain_blocked_count: int
    invalid_relation_blocked_count: int
    review_required_blocked_count: int
    info_only_blocked_count: int
    idempotency_key_duplicate_count: int
    rollback_plan_present: bool
    audit_event_count: int
    issues: list[str] = field(default_factory=list)
    recommended_next_step: str = ""


def validate_graph_write_plan(plan: ConfirmedGraphWritePlan) -> GraphWriteGovernanceReport:
    issues: list[str] = []
    production_write_blocked = False
    if plan.production_write:
        production_write_blocked = True
        issues.append("PRODUCTION_WRITE_BLOCKED")
    if not _is_test_namespace(plan.target_namespace):
        issues.append("TARGET_NAMESPACE_NOT_TEST")
    if plan.target_graph_type == TARGET_FORMAL_GRAPH:
        issues.append("FORMAL_GRAPH_DISABLED_BY_DEFAULT")

    confirmed_objects = [
        *plan.confirmed_entities,
        *plan.confirmed_relationships,
        *plan.confirmed_version_relations,
    ]
    missing_evidence_count = sum(1 for item in confirmed_objects if not _has_evidence(item))
    if missing_evidence_count:
        issues.append("CONFIRMED_OBJECT_MISSING_EVIDENCE")

    duplicate_count = _duplicate_count(plan.idempotency_keys)
    if duplicate_count:
        issues.append("DUPLICATE_IDEMPOTENCY_KEY")

    rollback_present = plan.rollback_plan is not None
    if not rollback_present:
        issues.append("ROLLBACK_PLAN_MISSING")
    if not plan.audit_events:
        issues.append("AUDIT_EVENTS_MISSING")
    if any(not item.audit_metadata.get("sidecarId") for item in confirmed_objects):
        issues.append("SIDECAR_METADATA_MISSING")

    missing_manifest_count = _blocked_count(plan, "MISSING_MANIFEST")
    version_uncertain_count = _blocked_count(plan, "VERSION")
    invalid_relation_count = _blocked_count(plan, "INVALID_RELATION")
    review_required_count = _blocked_count(plan, "REVIEW_REQUIRED")
    info_only_count = _blocked_count(plan, "INFO_ONLY")

    pass_status = FAIL if issues else PASS
    return GraphWriteGovernanceReport(
        pass_status=pass_status,
        production_write_blocked=production_write_blocked,
        missing_manifest_count=missing_manifest_count,
        missing_evidence_count=missing_evidence_count,
        version_uncertain_blocked_count=version_uncertain_count,
        invalid_relation_blocked_count=invalid_relation_count,
        review_required_blocked_count=review_required_count,
        info_only_blocked_count=info_only_count,
        idempotency_key_duplicate_count=duplicate_count,
        rollback_plan_present=rollback_present,
        audit_event_count=len(plan.audit_events),
        issues=issues,
        recommended_next_step=_recommended_next_step(issues, plan),
    )


def serialize_graph_write_governance_report(
    report: GraphWriteGovernanceReport,
) -> dict[str, Any]:
    return asdict(report)


def _has_evidence(item: ConfirmedGraphObject) -> bool:
    evidence = item.evidence
    has_source = bool(evidence.get("sourceUsId"))
    has_text_unit = bool(evidence.get("textUnitId") or evidence.get("source_id"))
    has_span_or_hash = bool(evidence.get("sourceSpan") or evidence.get("textHash"))
    has_text = bool(evidence.get("evidenceText"))
    return has_source and has_text_unit and has_span_or_hash and has_text


def _duplicate_count(values: list[str]) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def _blocked_count(plan: ConfirmedGraphWritePlan, token: str) -> int:
    return sum(
        1
        for item in [*plan.blocked_items, *plan.needs_review_items]
        if any(token in reason for reason in item.blocking_reasons)
    )


def _is_test_namespace(namespace: str) -> bool:
    lowered = namespace.lower()
    return "test" in lowered or "dsl_test" in lowered


def _recommended_next_step(issues: list[str], plan: ConfirmedGraphWritePlan) -> str:
    if "PRODUCTION_WRITE_BLOCKED" in issues or "TARGET_NAMESPACE_NOT_TEST" in issues:
        return "DO_NOT_WRITE_GRAPH"
    if "ROLLBACK_PLAN_MISSING" in issues:
        return "FIX_ROLLBACK_PLAN"
    if plan.needs_review_items:
        return "COLLECT_REVIEWER_MANIFEST"
    if plan.blocked_items:
        return "FIX_PROMOTION_BLOCKERS"
    return "READY_FOR_TEST_NAMESPACE_CONFIRMED_GRAPH_DRY_RUN"


__all__ = [
    "FAIL",
    "PASS",
    "WARN",
    "GraphWriteGovernanceReport",
    "serialize_graph_write_governance_report",
    "validate_graph_write_plan",
]
