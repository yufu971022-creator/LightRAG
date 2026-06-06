from __future__ import annotations

from .version_relation_builder import build_version_relations
from .version_relation_policy import VersionRelationPolicy
from .version_relation_types import (
    RuleVersionNode,
    VersionCoverageReport,
    VersionRelation,
    VersionedSemanticObject,
)


def optimized_version_relation_policy() -> VersionRelationPolicy:
    return VersionRelationPolicy(
        allow_singleton_no_conflict_as_test_safe=True,
        generate_version_review_for_singleton=False,
        require_explicit_supersedes_evidence=True,
        allow_source_order_supersedes=False,
        allow_supersedes_from_source_order=False,
        allow_weak_keyword_supersedes=False,
        require_evidence_for_version_relation=True,
        formal_graph_requires_explicit_current=True,
    )


def build_optimized_version_relations(
    versioned_objects: list[VersionedSemanticObject],
) -> tuple[list[RuleVersionNode], list[VersionRelation], VersionCoverageReport]:
    return build_version_relations(
        versioned_objects,
        policy=optimized_version_relation_policy(),
    )


__all__ = [
    "build_optimized_version_relations",
    "optimized_version_relation_policy",
]
