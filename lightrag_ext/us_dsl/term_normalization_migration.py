from __future__ import annotations

from collections import defaultdict
from typing import Any

from .scoped_term_resolver import resolve_term
from .semantic_identity import build_semantic_identity_key, stable_semantic_object_id, stable_version_group_key
from .term_normalization_types import TermNormalizationMigrationPlan, TermScope
from .term_registry import TermRegistry


def build_term_normalization_migration_plan(objects: list[dict[str, Any]], *, registry: TermRegistry) -> TermNormalizationMigrationPlan:
    identity_groups: dict[str, list[str]] = defaultdict(list)
    alias_groups: dict[str, list[str]] = defaultdict(list)
    conflict_groups: list[list[str]] = []
    candidate_groups: list[list[str]] = []
    planned_actions: list[dict[str, Any]] = []
    rebuild_required: set[str] = set()
    sidecar_only = 0
    version_group_rekey = 0
    for obj in objects:
        scope = TermScope(
            system_name=obj.get("system_name"),
            module_code=obj.get("module_code"),
            domain_code=obj.get("domain_code"),
            feature_key=obj.get("feature_key"),
            object_type=obj.get("object_type"),
        )
        decision = resolve_term(str(obj["canonical_name"]), scope=scope, registry=registry)
        if decision.decision == "CONFLICT":
            conflict_groups.append([str(obj["semantic_object_id"])])
            planned_actions.append({"action": "TERM_AMBIGUITY_REVIEW", "semantic_object_id": obj["semantic_object_id"], "term": obj["canonical_name"]})
            continue
        identity_key = build_semantic_identity_key(decision, scope=scope, object_type=str(obj["object_type"]), rule_dimension=obj.get("rule_dimension"))
        new_id = stable_semantic_object_id(identity_key)
        identity_groups[new_id].append(str(obj["semantic_object_id"]))
        alias_groups[new_id].append(str(obj["canonical_name"]))
        expected_vg = stable_version_group_key(identity_key)
        if obj.get("version_group_key") and obj.get("version_group_key") != expected_vg:
            version_group_rekey += 1
        if decision.decision == "CANDIDATE_REVIEW":
            candidate_groups.append([str(obj["semantic_object_id"])])
            planned_actions.append({"action": "REVIEW_CANDIDATE_ALIAS", "semantic_object_id": obj["semantic_object_id"], "term": obj["canonical_name"]})
        elif str(obj["semantic_object_id"]) != new_id:
            rebuild_required.add(str(obj["semantic_object_id"]))
            planned_actions.append({"action": "MERGE_OR_REBUILD_TEST_OBJECT", "from": obj["semantic_object_id"], "to": new_id})
        else:
            sidecar_only += 1
    confirmed_merge_groups = [sorted(ids) for ids in identity_groups.values() if len(ids) > 1]
    affected = sorted({item for group in confirmed_merge_groups + candidate_groups + conflict_groups for item in group} | rebuild_required)
    return TermNormalizationMigrationPlan(
        affected_semantic_object_ids=affected,
        alias_groups={key: sorted(set(values)) for key, values in sorted(alias_groups.items())},
        merge_candidate_groups=candidate_groups,
        confirmed_merge_groups=confirmed_merge_groups,
        conflict_groups=conflict_groups,
        version_group_rekey_count=version_group_rekey,
        graph_rebuild_required_count=len(rebuild_required),
        sidecar_only_update_count=sidecar_only,
        planned_actions=planned_actions,
    )
