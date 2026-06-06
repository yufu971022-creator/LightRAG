from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from .lc_mini_graph_smoke import LcMiniGraphSmokeConfig, build_lc_mini_kg_payload
from .version_relation_builder import build_version_relations, extract_versioned_semantic_objects
from .version_relation_policy import (
    VersionRelationPolicy,
    has_explicit_supersedes_signal,
    has_weak_version_keyword,
)
from .version_relation_types import (
    REL_VERSION_REVIEW_REQUIRED,
    VERSION_STATUS_CURRENT,
    VersionRelation,
    VersionedSemanticObject,
)


SINGLETON_NO_CONFLICT = "SINGLETON_NO_CONFLICT"
EXPLICIT_CURRENT = "EXPLICIT_CURRENT"
EXPLICIT_SUPERSEDES = "EXPLICIT_SUPERSEDES"
WEAK_VERSION_KEYWORD_ONLY = "WEAK_VERSION_KEYWORD_ONLY"
MULTI_VERSION_UNKNOWN = "MULTI_VERSION_UNKNOWN"
CONFLICT_WITHOUT_SUPERSEDES = "CONFLICT_WITHOUT_SUPERSEDES"
MISSING_EVIDENCE = "MISSING_EVIDENCE"
UNSAFE_SUPERSEDES_BLOCKED = "UNSAFE_SUPERSEDES_BLOCKED"
VERSION_STATUS_UNCERTAIN = "VERSION_STATUS_UNCERTAIN"
TRUE_REVIEW_REQUIRED = "TRUE_REVIEW_REQUIRED"


@dataclass(frozen=True)
class VersionIssueTriageItem:
    version_group_key: str
    object_type: str | None
    object_key: str | None
    rule_dimension: str | None
    source_us_ids: list[str]
    version_count: int
    category: str
    current_policy_decision: str
    optimized_policy_decision: str
    review_required_before: bool
    review_required_after: bool
    safe_to_reduce_review: bool
    requires_human_review: bool
    evidence_summary: dict[str, Any]
    reason: str
    risks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VersionIssueTriageReport:
    total_version_groups: int
    singleton_no_conflict_count: int
    explicit_current_count: int
    explicit_supersedes_count: int
    weak_version_keyword_only_count: int
    multi_version_unknown_count: int
    conflict_without_supersedes_count: int
    missing_evidence_count: int
    true_review_required_count: int
    review_required_before_count: int
    review_required_after_count: int
    review_required_reduction_count: int
    unsafe_supersedes_blocked_count: int
    pass_status: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommended_next_step: str = ""
    items: list[VersionIssueTriageItem] = field(default_factory=list)


def build_version_issue_triage_report(
    versioned_objects: list[VersionedSemanticObject],
    version_relations_before: list[VersionRelation] | None = None,
    policy_before: VersionRelationPolicy | None = None,
    policy_after: VersionRelationPolicy | None = None,
) -> VersionIssueTriageReport:
    policy_before = policy_before or VersionRelationPolicy(
        allow_singleton_no_conflict_as_test_safe=False,
        allow_explicit_current_as_test_safe=False,
        generate_version_review_for_singleton=True,
    )
    policy_after = policy_after or VersionRelationPolicy()
    before_relations = version_relations_before
    if before_relations is None:
        _nodes, before_relations, _report = build_version_relations(
            versioned_objects,
            policy=policy_before,
        )
    _nodes, after_relations, after_report = build_version_relations(
        versioned_objects,
        policy=policy_after,
    )
    before_review_groups = _review_groups(before_relations)
    after_review_groups = _review_groups(after_relations)
    unsafe_supersedes = _unsafe_supersedes_count(versioned_objects, policy_after)

    items: list[VersionIssueTriageItem] = []
    for group_key, group_items in _group_by_key(versioned_objects).items():
        category, reason, risks = _categorize(group_items, policy_after)
        before = group_key in before_review_groups
        after = group_key in after_review_groups
        items.append(
            VersionIssueTriageItem(
                version_group_key=group_key,
                object_type=group_items[0].object_type if group_items else None,
                object_key=group_items[0].object_key if group_items else None,
                rule_dimension=group_items[0].rule_dimension if group_items else None,
                source_us_ids=_unique(item.source_us_id for item in group_items),
                version_count=len(group_items),
                category=category,
                current_policy_decision="REVIEW_REQUIRED" if before else "NO_REVIEW",
                optimized_policy_decision="REVIEW_REQUIRED" if after else "NO_REVIEW",
                review_required_before=before,
                review_required_after=after,
                safe_to_reduce_review=before and not after and category in {
                    SINGLETON_NO_CONFLICT,
                    EXPLICIT_CURRENT,
                },
                requires_human_review=after or category in {
                    WEAK_VERSION_KEYWORD_ONLY,
                    MULTI_VERSION_UNKNOWN,
                    CONFLICT_WITHOUT_SUPERSEDES,
                    MISSING_EVIDENCE,
                    UNSAFE_SUPERSEDES_BLOCKED,
                    TRUE_REVIEW_REQUIRED,
                },
                evidence_summary=_evidence_summary(group_items),
                reason=reason,
                risks=risks,
            )
        )

    counts = Counter(item.category for item in items)
    before_count = sum(1 for item in items if item.review_required_before)
    after_count = sum(1 for item in items if item.review_required_after)
    issues = list(after_report.issues)
    if unsafe_supersedes:
        issues.append({"code": UNSAFE_SUPERSEDES_BLOCKED, "count": unsafe_supersedes})
    return VersionIssueTriageReport(
        total_version_groups=len(items),
        singleton_no_conflict_count=counts[SINGLETON_NO_CONFLICT],
        explicit_current_count=counts[EXPLICIT_CURRENT],
        explicit_supersedes_count=counts[EXPLICIT_SUPERSEDES],
        weak_version_keyword_only_count=counts[WEAK_VERSION_KEYWORD_ONLY],
        multi_version_unknown_count=counts[MULTI_VERSION_UNKNOWN],
        conflict_without_supersedes_count=counts[CONFLICT_WITHOUT_SUPERSEDES],
        missing_evidence_count=counts[MISSING_EVIDENCE],
        true_review_required_count=sum(
            counts[category]
            for category in (
                WEAK_VERSION_KEYWORD_ONLY,
                MULTI_VERSION_UNKNOWN,
                CONFLICT_WITHOUT_SUPERSEDES,
                MISSING_EVIDENCE,
                UNSAFE_SUPERSEDES_BLOCKED,
                TRUE_REVIEW_REQUIRED,
            )
        ),
        review_required_before_count=before_count,
        review_required_after_count=after_count,
        review_required_reduction_count=max(0, before_count - after_count),
        unsafe_supersedes_blocked_count=unsafe_supersedes,
        pass_status="PASS" if after_count <= before_count and unsafe_supersedes >= 0 else "FAIL",
        issues=issues,
        recommended_next_step=(
            "TUNE_TRUE_VERSION_REVIEW_CASES"
            if after_count
            else "REVIEW_POLICY_BLOCKED_OBJECTS"
        ),
        items=items,
    )


def build_lc_version_issue_triage_report() -> VersionIssueTriageReport:
    payload = build_lc_mini_kg_payload(
        LcMiniGraphSmokeConfig(max_chunks=100, max_entities=100, max_relationships=100)
    )
    return build_version_issue_triage_report(
        extract_versioned_semantic_objects(kg_payload=payload)
    )


def serialize_version_issue_triage_report(report: VersionIssueTriageReport) -> dict[str, Any]:
    return asdict(report)


def _categorize(
    group_items: list[VersionedSemanticObject],
    policy: VersionRelationPolicy,
) -> tuple[str, str, list[str]]:
    risks: list[str] = []
    if any(not _has_evidence(item) for item in group_items):
        return MISSING_EVIDENCE, "Missing source evidence prevents version safety.", risks
    if any(_explicit_supersedes_without_evidence(item) for item in group_items):
        return UNSAFE_SUPERSEDES_BLOCKED, "Supersedes target exists without explicit evidence.", risks
    if any(has_explicit_supersedes_signal(item.raw, item.evidence_text) for item in group_items):
        return EXPLICIT_SUPERSEDES, "Explicit supersedes evidence is present.", risks
    if _group_has_conflict(group_items, policy):
        return CONFLICT_WITHOUT_SUPERSEDES, "Conflicting rule text requires review.", risks
    latest_true = [item for item in group_items if item.latest_flag is True]
    if len(latest_true) > 1:
        return TRUE_REVIEW_REQUIRED, "Multiple latestFlag=true values require review.", risks
    if any(has_weak_version_keyword(item.raw, item.evidence_text) for item in group_items):
        return WEAK_VERSION_KEYWORD_ONLY, "Weak version keyword has no replacement target.", risks
    if len(group_items) > 1 and not latest_true:
        return MULTI_VERSION_UNKNOWN, "Multiple versions lack unique current evidence.", risks
    if len(latest_true) == 1 or any(item.version_status == VERSION_STATUS_CURRENT for item in group_items):
        return EXPLICIT_CURRENT, "Unique latest/current evidence does not need review.", risks
    if len(group_items) == 1:
        return SINGLETON_NO_CONFLICT, "Single version group has complete evidence and no conflict.", risks
    return VERSION_STATUS_UNCERTAIN, "Version status remains uncertain.", risks


def _review_groups(relations: list[VersionRelation]) -> set[str]:
    return {
        str(item.metadata.get("versionGroupKey") or item.metadata.get("version_group_key"))
        for item in relations
        if item.relation_type == REL_VERSION_REVIEW_REQUIRED
    }


def _unsafe_supersedes_count(
    versioned_objects: list[VersionedSemanticObject],
    policy: VersionRelationPolicy,
) -> int:
    if not policy.require_explicit_supersedes_evidence:
        return 0
    return sum(1 for item in versioned_objects if _explicit_supersedes_without_evidence(item))


def _explicit_supersedes_without_evidence(item: VersionedSemanticObject) -> bool:
    return bool(item.supersedes) and not has_explicit_supersedes_signal(item.raw, item.evidence_text)


def _group_has_conflict(
    group_items: list[VersionedSemanticObject],
    policy: VersionRelationPolicy,
) -> bool:
    for index, left in enumerate(group_items):
        for right in group_items[index + 1 :]:
            if _has_rule_conflict(left.rule_text, right.rule_text, policy):
                return True
    return False


def _has_rule_conflict(
    left: str | None,
    right: str | None,
    policy: VersionRelationPolicy,
) -> bool:
    left_text = str(left or "").lower()
    right_text = str(right or "").lower()
    if not left_text or not right_text or left_text == right_text:
        return False
    for positive, negative in policy.opposite_keyword_pairs:
        positive = positive.lower()
        negative = negative.lower()
        if (positive in left_text and negative in right_text) or (
            negative in left_text and positive in right_text
        ):
            return True
    return False


def _has_evidence(item: VersionedSemanticObject) -> bool:
    return bool(
        item.source_us_id
        and item.source_text_unit_id
        and item.text_hash
        and (item.evidence_text or item.source_span)
    )


def _group_by_key(
    objects: list[VersionedSemanticObject],
) -> dict[str, list[VersionedSemanticObject]]:
    groups: dict[str, list[VersionedSemanticObject]] = defaultdict(list)
    for item in objects:
        groups[item.version_group_key].append(item)
    return dict(groups)


def _evidence_summary(group_items: list[VersionedSemanticObject]) -> dict[str, Any]:
    return {
        "sourceUsIds": _unique(item.source_us_id for item in group_items),
        "textUnitIds": _unique(item.source_text_unit_id for item in group_items),
        "textHashCount": len({item.text_hash for item in group_items if item.text_hash}),
        "hasEvidenceText": all(bool(item.evidence_text) for item in group_items),
        "hasSourceSpan": all(bool(item.source_span) for item in group_items),
    }


def _unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(str(value))
    return result


__all__ = [
    "CONFLICT_WITHOUT_SUPERSEDES",
    "EXPLICIT_CURRENT",
    "EXPLICIT_SUPERSEDES",
    "MISSING_EVIDENCE",
    "MULTI_VERSION_UNKNOWN",
    "SINGLETON_NO_CONFLICT",
    "TRUE_REVIEW_REQUIRED",
    "UNSAFE_SUPERSEDES_BLOCKED",
    "VERSION_STATUS_UNCERTAIN",
    "WEAK_VERSION_KEYWORD_ONLY",
    "VersionIssueTriageItem",
    "VersionIssueTriageReport",
    "build_lc_version_issue_triage_report",
    "build_version_issue_triage_report",
    "serialize_version_issue_triage_report",
]
