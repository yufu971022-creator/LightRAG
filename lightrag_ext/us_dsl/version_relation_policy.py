from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EXPLICIT_SUPERSEDES_KEYS = (
    "supersedes",
    "supersedesVersion",
    "oldVersionId",
    "replaces",
    "replacedVersion",
)

EXPLICIT_SUPERSEDES_TERMS = (
    "supersedes",
    "replaces",
    "replace",
    "替代",
    "替换",
    "废弃旧规则",
    "覆盖旧规则",
    "本规则覆盖",
)

OPPOSITE_KEYWORD_PAIRS = (
    ("editable", "readonly"),
    ("editable", "read-only"),
    ("can edit", "cannot edit"),
    ("generate", "not generate"),
    ("生成", "不生成"),
    ("可修改", "不可修改"),
    ("只读", "可编辑"),
    ("yes", "no"),
)

WEAK_VERSION_TERMS = (
    "新增",
    "优化",
    "调整",
    "变更",
    "更新",
    "废弃",
    "new",
    "optimize",
    "adjust",
    "changed",
    "update",
    "updated",
    "deprecated",
)


@dataclass(frozen=True)
class VersionRelationPolicy:
    explicit_supersedes_keys: tuple[str, ...] = EXPLICIT_SUPERSEDES_KEYS
    explicit_supersedes_terms: tuple[str, ...] = EXPLICIT_SUPERSEDES_TERMS
    opposite_keyword_pairs: tuple[tuple[str, str], ...] = OPPOSITE_KEYWORD_PAIRS
    weak_version_terms: tuple[str, ...] = WEAK_VERSION_TERMS
    generate_review_required_for_unknown_status: bool = True
    generate_version_review_for_singleton: bool = False
    allow_singleton_no_conflict_as_test_safe: bool = True
    allow_explicit_current_as_test_safe: bool = True
    singleton_status_label: str = "SingleVersionNoConflict"
    require_explicit_supersedes_evidence: bool = True
    allow_supersedes_from_source_order: bool = False
    allow_source_order_supersedes: bool = False
    allow_weak_keyword_supersedes: bool = False
    require_evidence_for_version_relation: bool = True
    formal_graph_requires_explicit_current: bool = True
    allowed_version_relations: set[str] = field(
        default_factory=lambda: {
            "HasVersion",
            "Supersedes",
            "VersionConflictWith",
            "VersionReviewRequired",
            "DefinesVersion",
            "DerivedFromVersionEvidence",
        }
    )


def has_explicit_supersedes_signal(raw: dict[str, Any], evidence_text: str | None) -> bool:
    if any(raw.get(key) not in (None, "", []) for key in EXPLICIT_SUPERSEDES_KEYS):
        return True
    text = str(evidence_text or "").lower()
    return any(term.lower() in text for term in EXPLICIT_SUPERSEDES_TERMS)


def has_weak_version_keyword(raw: dict[str, Any], evidence_text: str | None) -> bool:
    keywords = raw.get("versionKeywords") or raw.get("keywords") or []
    if isinstance(keywords, str):
        keyword_text = keywords.lower()
    elif isinstance(keywords, list):
        keyword_text = " ".join(str(item).lower() for item in keywords)
    else:
        keyword_text = ""
    text = f"{keyword_text} {str(evidence_text or '').lower()}"
    return any(term.lower() in text for term in WEAK_VERSION_TERMS)


__all__ = [
    "EXPLICIT_SUPERSEDES_KEYS",
    "EXPLICIT_SUPERSEDES_TERMS",
    "OPPOSITE_KEYWORD_PAIRS",
    "WEAK_VERSION_TERMS",
    "VersionRelationPolicy",
    "has_explicit_supersedes_signal",
    "has_weak_version_keyword",
]
