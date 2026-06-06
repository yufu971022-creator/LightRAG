from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import hashlib
import json
from typing import Any

from .candidate_extraction import CandidateExtractionReport
from .candidate_types import CandidateEntity
from .kg_payload_types import DslKgPayload, KgEntity, KgRelationship
from .kg_schema_policy import TOP_LEVEL_ENTITY_TYPES
from .version_relation_policy import (
    VersionRelationPolicy,
    has_explicit_supersedes_signal,
    has_weak_version_keyword,
)
from .version_relation_types import (
    REL_HAS_VERSION,
    REL_SUPERSEDES,
    REL_VERSION_CONFLICT,
    REL_VERSION_REVIEW_REQUIRED,
    VERSION_STATUS_REVIEW_REQUIRED,
    VERSION_STATUS_CURRENT,
    VERSION_STATUS_SINGLE_VERSION_NO_CONFLICT,
    VERSION_STATUS_UNKNOWN,
    RuleVersionNode,
    VersionCoverageReport,
    VersionRelation,
    VersionedSemanticObject,
    serialize_version_coverage_report,
)


VERSIONED_ENTITY_TYPES = TOP_LEVEL_ENTITY_TYPES - {"UserStory", "FeatureCatalog"}
VERSION_RULE_RELATIONS = {
    REL_HAS_VERSION,
    REL_SUPERSEDES,
    REL_VERSION_CONFLICT,
    REL_VERSION_REVIEW_REQUIRED,
}


def extract_versioned_semantic_objects(
    *,
    kg_payload: DslKgPayload | None = None,
    candidate_extraction_report: CandidateExtractionReport | None = None,
    candidate_review_report: Any = None,
    ingestion_payload: Any = None,
    dsl_result: dict[str, Any] | None = None,
) -> list[VersionedSemanticObject]:
    objects: list[VersionedSemanticObject] = []
    allowed_candidate_names: set[str] | None = None
    if kg_payload is not None:
        objects.extend(_objects_from_kg_payload(kg_payload))
        allowed_candidate_names = {entity.entity_name for entity in kg_payload.entities}
    if candidate_extraction_report is not None:
        objects.extend(
            _objects_from_candidate_report(
                candidate_extraction_report,
                allowed_names=allowed_candidate_names,
            )
        )
    objects.extend(_objects_from_dsl_result(dsl_result))
    return _dedupe_objects(objects)


def build_version_relations(
    versioned_objects: list[VersionedSemanticObject],
    *,
    policy: VersionRelationPolicy | None = None,
) -> tuple[list[RuleVersionNode], list[VersionRelation], VersionCoverageReport]:
    policy = policy or VersionRelationPolicy()
    issues: list[dict[str, Any]] = []
    missing_group_key_count = 0
    missing_evidence_count = 0
    unsafe_supersedes_blocked = 0
    nodes_by_id: dict[str, RuleVersionNode] = {}
    relations: list[VersionRelation] = []
    valid_objects: list[VersionedSemanticObject] = []

    for item in versioned_objects:
        if not item.version_group_key:
            missing_group_key_count += 1
            issues.append(_issue("MISSING_VERSION_GROUP_KEY", item.object_key))
            continue
        if not _has_evidence(item):
            missing_evidence_count += 1
            issues.append(_issue("MISSING_VERSION_EVIDENCE", item.object_key))
            continue
        valid_objects.append(item)

    valid_objects = _apply_optimized_version_policy(valid_objects, policy)
    groups = _group_by_version_key(valid_objects)

    for item in valid_objects:
        node = _rule_version_node(item)
        nodes_by_id.setdefault(node.version_id, node)
        relations.append(_has_version_relation(item, node))

    for item in valid_objects:
        src_node = nodes_by_id[_rule_version_id(item)]
        for superseded in item.supersedes:
            if policy.require_explicit_supersedes_evidence and not has_explicit_supersedes_signal(
                item.raw,
                item.evidence_text,
            ):
                unsafe_supersedes_blocked += 1
                issues.append(_issue("UNSAFE_SUPERSEDES_BLOCKED", item.object_key))
                continue
            target_node = _superseded_target_node(item, superseded, groups.get(item.version_group_key, []))
            nodes_by_id.setdefault(target_node.version_id, target_node)
            relations.append(_supersedes_relation(item, src_node, target_node, superseded))

    for group_items in groups.values():
        group_nodes = [nodes_by_id[_rule_version_id(item)] for item in group_items]
        relations.extend(_group_review_relations(group_items, group_nodes, policy=policy))
        relations.extend(_group_conflict_relations(group_items, group_nodes, policy=policy))

    relations = _dedupe_relations(relations)
    report = VersionCoverageReport(
        versioned_object_count=len(versioned_objects),
        rule_version_node_count=len(nodes_by_id),
        has_version_count=sum(1 for item in relations if item.relation_type == REL_HAS_VERSION),
        supersedes_count=sum(1 for item in relations if item.relation_type == REL_SUPERSEDES),
        version_conflict_count=sum(1 for item in relations if item.relation_type == REL_VERSION_CONFLICT),
        version_review_required_count=sum(
            1 for item in relations if item.relation_type == REL_VERSION_REVIEW_REQUIRED
        ),
        missing_version_group_key_count=missing_group_key_count,
        missing_evidence_count=missing_evidence_count,
        unsafe_supersedes_blocked_count=unsafe_supersedes_blocked,
        pass_status="PASS" if missing_evidence_count == 0 and missing_group_key_count == 0 else "FAIL",
        issues=issues,
    )
    return list(nodes_by_id.values()), relations, report


def augment_kg_payload_with_version_relations(
    payload: DslKgPayload,
    *,
    candidate_extraction_report: CandidateExtractionReport | None = None,
    candidate_review_report: Any = None,
    ingestion_payload: Any = None,
    dsl_result: dict[str, Any] | None = None,
    policy: VersionRelationPolicy | None = None,
) -> DslKgPayload:
    versioned_objects = extract_versioned_semantic_objects(
        kg_payload=payload,
        candidate_extraction_report=candidate_extraction_report,
        candidate_review_report=candidate_review_report,
        ingestion_payload=ingestion_payload,
        dsl_result=dsl_result,
    )
    nodes, relations, report = build_version_relations(versioned_objects, policy=policy)
    entities = _merge_entities(payload.entities, [_entity_from_version_node(node) for node in nodes])
    relationships = _merge_relationships(
        payload.relationships,
        [_relationship_from_version_relation(item) for item in relations],
    )
    version_mapping = dict(payload.version_mapping)
    for item in versioned_objects:
        version_mapping[item.object_key] = {
            "versionGroupKey": item.version_group_key,
            "ruleVersion": item.rule_version,
            "latestFlag": item.latest_flag,
            "versionStatus": item.version_status or VERSION_STATUS_UNKNOWN,
            "supersedes": list(item.supersedes),
            "sourceUsId": item.source_us_id,
            "sourceTextUnitId": item.source_text_unit_id,
        }
    return DslKgPayload(
        chunks=list(payload.chunks),
        entities=entities,
        relationships=relationships,
        metadata={
            **payload.metadata,
            "versionRelationsEnabled": True,
            "versionRelationCoverage": serialize_version_coverage_report(report),
        },
        issues=list(payload.issues),
        summary={
            **payload.summary,
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "versioned_object_count": report.versioned_object_count,
            "rule_version_node_count": report.rule_version_node_count,
            "has_version_count": report.has_version_count,
            "supersedes_count": report.supersedes_count,
            "version_conflict_count": report.version_conflict_count,
            "version_review_required_count": report.version_review_required_count,
        },
        entity_vdb_payload=list(payload.entity_vdb_payload),
        relationship_vdb_payload=list(payload.relationship_vdb_payload),
        evidence_mapping=dict(payload.evidence_mapping),
        version_mapping=version_mapping,
    )


def build_lc_version_relation_coverage_report() -> VersionCoverageReport:
    from .lc_mini_graph_smoke import LcMiniGraphSmokeConfig, build_lc_mini_kg_payload

    payload = build_lc_mini_kg_payload(
        LcMiniGraphSmokeConfig(
            max_chunks=100,
            max_entities=100,
            max_relationships=100,
        )
    )
    objects = extract_versioned_semantic_objects(kg_payload=payload)
    _nodes, _relations, report = build_version_relations(objects)
    return report


def _objects_from_kg_payload(payload: DslKgPayload) -> list[VersionedSemanticObject]:
    values: list[VersionedSemanticObject] = []
    for entity in payload.entities:
        if entity.entity_type not in VERSIONED_ENTITY_TYPES and entity.entity_type != "CandidateEntity":
            continue
        metadata = dict(entity.metadata)
        values.append(
            _versioned_object(
                module_code=_string_or_none(metadata.get("moduleCode")),
                domain_code=_string_or_none(metadata.get("domainCode")),
                feature_key=_string_or_none(metadata.get("featureKey")),
                object_type=entity.entity_type,
                object_key=entity.entity_name,
                rule_dimension=_rule_dimension(entity.entity_type, metadata),
                source_us_id=_string_or_none(metadata.get("sourceUsId")),
                source_text_unit_id=_string_or_none(metadata.get("textUnitId")) or entity.source_id,
                section_type=_string_or_none(metadata.get("sectionType")),
                evidence_text=_string_or_none(metadata.get("evidenceText")) or entity.description,
                source_span=_dict_or_none(metadata.get("sourceSpan")),
                text_hash=_string_or_none(metadata.get("textHash")),
                rule_text=_string_or_none(metadata.get("ruleText"))
                or _string_or_none(metadata.get("evidenceText"))
                or entity.description,
                latest_flag=_bool_or_none(metadata.get("latestFlag")),
                version_status=_version_status(metadata.get("versionStatus")),
                rule_version=_string_or_none(metadata.get("ruleVersion")),
                supersedes=_string_list(metadata.get("supersedes")),
                version_keywords=_version_keywords(metadata),
                raw=metadata,
            )
        )
    return values


def _objects_from_candidate_report(
    report: CandidateExtractionReport,
    *,
    allowed_names: set[str] | None = None,
) -> list[VersionedSemanticObject]:
    values: list[VersionedSemanticObject] = []
    for candidate in report.candidate_entities:
        if allowed_names is not None and candidate.entity_name not in allowed_names:
            continue
        values.append(_versioned_object_from_candidate(candidate))
    return values


def _versioned_object_from_candidate(candidate: CandidateEntity) -> VersionedSemanticObject:
    raw = dict(candidate.raw)
    return _versioned_object(
        module_code=_string_or_none(raw.get("moduleCode")),
        domain_code=candidate.domain_code,
        feature_key=candidate.feature_key,
        object_type=candidate.entity_type,
        object_key=candidate.entity_name,
        rule_dimension=_rule_dimension(candidate.entity_type, raw),
        source_us_id=candidate.source_us_id,
        source_text_unit_id=candidate.source_text_unit_id,
        section_type=candidate.section_type,
        evidence_text=candidate.evidence_text,
        source_span=candidate.source_span,
        text_hash=candidate.text_hash,
        rule_text=_string_or_none(raw.get("ruleText")) or candidate.evidence_text or candidate.description,
        latest_flag=_bool_or_none(raw.get("latestFlag")),
        version_status=_version_status(raw.get("versionStatus")),
        rule_version=_string_or_none(raw.get("ruleVersion") or raw.get("version") or raw.get("versionId")),
        supersedes=_string_list(raw.get("supersedes") or raw.get("supersedesVersion")),
        version_keywords=_version_keywords(raw),
        raw=raw,
    )


def _objects_from_dsl_result(dsl_result: dict[str, Any] | None) -> list[VersionedSemanticObject]:
    if not isinstance(dsl_result, dict):
        return []
    version_items = dsl_result.get("versionManagement") or dsl_result.get("versionContext") or []
    if isinstance(version_items, dict):
        version_items = version_items.get("items") or version_items.get("rules") or []
    if not isinstance(version_items, list):
        return []
    objects: list[VersionedSemanticObject] = []
    for index, item in enumerate(version_items):
        if not isinstance(item, dict):
            continue
        object_type = _string_or_none(item.get("objectType")) or "RuleAtom"
        object_key = _string_or_none(item.get("objectKey")) or _string_or_none(item.get("entityName"))
        feature_key = _string_or_none(item.get("featureKey"))
        if not object_key or not feature_key:
            continue
        objects.append(
            _versioned_object(
                module_code=_string_or_none(item.get("moduleCode")),
                domain_code=_string_or_none(item.get("domainCode")),
                feature_key=feature_key,
                object_type=object_type,
                object_key=object_key,
                rule_dimension=_string_or_none(item.get("ruleDimension")),
                source_us_id=_string_or_none(item.get("sourceUsId")),
                source_text_unit_id=_string_or_none(item.get("sourceTextUnitId"))
                or _string_or_none(item.get("textUnitId")),
                section_type=_string_or_none(item.get("sectionType")),
                evidence_text=_string_or_none(item.get("evidenceText")),
                source_span=_dict_or_none(item.get("sourceSpan")),
                text_hash=_string_or_none(item.get("textHash")) or f"dsl-version-{index}",
                rule_text=_string_or_none(item.get("ruleText")) or _string_or_none(item.get("evidenceText")),
                latest_flag=_bool_or_none(item.get("latestFlag")),
                version_status=_version_status(item.get("versionStatus")),
                rule_version=_string_or_none(item.get("ruleVersion")),
                supersedes=_string_list(item.get("supersedes")),
                version_keywords=_version_keywords(item),
                raw=item,
            )
        )
    return objects


def _versioned_object(
    *,
    module_code: str | None,
    domain_code: str | None,
    feature_key: str | None,
    object_type: str,
    object_key: str,
    rule_dimension: str | None,
    source_us_id: str | None,
    source_text_unit_id: str | None,
    section_type: str | None,
    evidence_text: str | None,
    source_span: dict[str, Any] | None,
    text_hash: str | None,
    rule_text: str | None,
    latest_flag: bool | None,
    version_status: str | None,
    rule_version: str | None,
    supersedes: list[str],
    version_keywords: list[str],
    raw: dict[str, Any],
) -> VersionedSemanticObject:
    normalized_status = version_status or VERSION_STATUS_UNKNOWN
    group_key = _version_group_key(
        module_code=module_code,
        domain_code=domain_code,
        feature_key=feature_key,
        object_type=object_type,
        object_key=object_key,
        rule_dimension=rule_dimension,
    )
    return VersionedSemanticObject(
        version_group_key=group_key,
        module_code=module_code,
        domain_code=domain_code,
        feature_key=feature_key,
        object_type=object_type,
        object_key=object_key,
        rule_dimension=rule_dimension,
        source_us_id=source_us_id,
        source_text_unit_id=source_text_unit_id,
        section_type=section_type,
        evidence_text=evidence_text,
        source_span=source_span,
        text_hash=text_hash,
        rule_text=rule_text,
        latest_flag=latest_flag,
        version_status=normalized_status,
        rule_version=rule_version,
        supersedes=supersedes,
        version_keywords=version_keywords,
        raw={**raw, "version_group_key": group_key},
    )


def _apply_optimized_version_policy(
    objects: list[VersionedSemanticObject],
    policy: VersionRelationPolicy,
) -> list[VersionedSemanticObject]:
    updated: list[VersionedSemanticObject] = []
    for group_items in _group_by_version_key(objects).values():
        latest_true = [item for item in group_items if item.latest_flag is True]
        multiple_latest = len(latest_true) > 1
        has_conflict = _group_has_conflict(group_items, policy)
        for item in group_items:
            if multiple_latest or has_conflict or _weak_keyword_without_explicit_supersedes(item, policy):
                updated.append(item)
                continue
            if item.version_status == VERSION_STATUS_CURRENT:
                updated.append(item)
                continue
            if (
                len(group_items) == 1
                and item.latest_flag is True
                and policy.allow_explicit_current_as_test_safe
            ):
                updated.append(
                    replace(
                        item,
                        version_status=VERSION_STATUS_CURRENT,
                        raw={
                            **item.raw,
                            "versionStatus": VERSION_STATUS_CURRENT,
                            "safeToTestGraph": True,
                            "safeToFormalGraph": False,
                            "versionTriageCategory": "EXPLICIT_CURRENT",
                        },
                    )
                )
                continue
            if (
                len(group_items) == 1
                and policy.allow_singleton_no_conflict_as_test_safe
                and not policy.generate_version_review_for_singleton
            ):
                status = policy.singleton_status_label or VERSION_STATUS_SINGLE_VERSION_NO_CONFLICT
                updated.append(
                    replace(
                        item,
                        version_status=status,
                        raw={
                            **item.raw,
                            "versionStatus": status,
                            "safeToTestGraph": True,
                            "safeToFormalGraph": False,
                            "versionTriageCategory": "SINGLETON_NO_CONFLICT",
                        },
                    )
                )
                continue
            updated.append(item)
    return updated


def _group_has_conflict(
    group_items: list[VersionedSemanticObject],
    policy: VersionRelationPolicy,
) -> bool:
    for left_index, left in enumerate(group_items):
        for right in group_items[left_index + 1 :]:
            if _has_rule_conflict(left.rule_text, right.rule_text, policy):
                return True
    return False


def _weak_keyword_without_explicit_supersedes(
    item: VersionedSemanticObject,
    policy: VersionRelationPolicy,
) -> bool:
    if policy.allow_weak_keyword_supersedes:
        return False
    return has_weak_version_keyword(item.raw, item.evidence_text) and not has_explicit_supersedes_signal(
        item.raw,
        item.evidence_text,
    )


def _status_requires_review(status: str | None) -> bool:
    return status in {VERSION_STATUS_UNKNOWN, VERSION_STATUS_REVIEW_REQUIRED}


def _rule_version_node(item: VersionedSemanticObject) -> RuleVersionNode:
    version_id = _rule_version_id(item)
    version_label = item.rule_version or f"{item.object_key}@{item.source_us_id or item.source_text_unit_id}"
    status = item.version_status or VERSION_STATUS_UNKNOWN
    review_required = _status_requires_review(status)
    metadata = _version_metadata(
        item,
        relation_type=None,
        requires_human_review=review_required,
        reason_code="RULE_VERSION_NODE",
    )
    return RuleVersionNode(
        version_id=version_id,
        version_group_key=item.version_group_key,
        version_label=version_label,
        source_us_id=item.source_us_id,
        source_text_unit_id=item.source_text_unit_id,
        rule_version=version_label,
        latest_flag=item.latest_flag,
        version_status=status,
        evidence_text=item.evidence_text,
        source_span=item.source_span,
        text_hash=item.text_hash,
        metadata=metadata,
    )


def _has_version_relation(item: VersionedSemanticObject, node: RuleVersionNode) -> VersionRelation:
    review_required = _status_requires_review(node.version_status)
    return VersionRelation(
        src_id=item.object_key,
        tgt_id=node.version_id,
        relation_type=REL_HAS_VERSION,
        description=f"{item.object_key} has version evidence {node.version_label}.",
        source_id=item.source_text_unit_id,
        evidence_text=item.evidence_text,
        confidence_score=0.9,
        safe_to_auto_accept=not review_required,
        requires_human_review=review_required,
        reason_code="HAS_VERSION_FROM_SEMANTIC_OBJECT",
        metadata=_version_metadata(
            item,
            relation_type=REL_HAS_VERSION,
            requires_human_review=review_required,
            reason_code="HAS_VERSION_FROM_SEMANTIC_OBJECT",
        ),
    )


def _superseded_target_node(
    item: VersionedSemanticObject,
    superseded: str,
    group_items: list[VersionedSemanticObject],
) -> RuleVersionNode:
    for candidate in group_items:
        if candidate.rule_version == superseded or _rule_version_id(candidate) == superseded:
            return _rule_version_node(candidate)
    target_item = replace(
        item,
        rule_version=superseded,
        latest_flag=False,
        version_status="Historical",
        raw={**item.raw, "ruleVersion": superseded, "latestFlag": False, "versionStatus": "Historical"},
    )
    return _rule_version_node(target_item)


def _supersedes_relation(
    item: VersionedSemanticObject,
    src_node: RuleVersionNode,
    target_node: RuleVersionNode,
    superseded: str,
) -> VersionRelation:
    return VersionRelation(
        src_id=src_node.version_id,
        tgt_id=target_node.version_id,
        relation_type=REL_SUPERSEDES,
        description=f"{src_node.version_label} supersedes {superseded}.",
        source_id=item.source_text_unit_id,
        evidence_text=item.evidence_text,
        confidence_score=0.95,
        safe_to_auto_accept=False,
        requires_human_review=False,
        reason_code="EXPLICIT_SUPERSEDES_EVIDENCE",
        metadata=_version_metadata(
            item,
            relation_type=REL_SUPERSEDES,
            requires_human_review=False,
            reason_code="EXPLICIT_SUPERSEDES_EVIDENCE",
            extra={"supersededVersion": superseded},
        ),
    )


def _group_review_relations(
    group_items: list[VersionedSemanticObject],
    group_nodes: list[RuleVersionNode],
    *,
    policy: VersionRelationPolicy,
) -> list[VersionRelation]:
    relations: list[VersionRelation] = []
    latest_true = [item for item in group_items if item.latest_flag is True]
    multiple_latest = len(latest_true) > 1
    multi_version_unknown = (
        len(group_items) > 1
        and not latest_true
        and not any(item.supersedes for item in group_items)
    )
    for item, node in zip(group_items, group_nodes, strict=False):
        status = item.version_status or VERSION_STATUS_UNKNOWN
        singleton_safe = (
            len(group_items) == 1
            and status == policy.singleton_status_label
            and policy.allow_singleton_no_conflict_as_test_safe
        )
        weak_keyword_only = _weak_keyword_without_explicit_supersedes(item, policy)
        needs_unknown_review = (
            policy.generate_review_required_for_unknown_status
            and status in {VERSION_STATUS_UNKNOWN, VERSION_STATUS_REVIEW_REQUIRED}
            and not item.supersedes
            and not singleton_safe
        )
        if not (
            multiple_latest
            or multi_version_unknown
            or weak_keyword_only
            or needs_unknown_review
        ):
            continue
        if multiple_latest:
            reason = "MULTIPLE_LATEST_FLAGS"
        elif weak_keyword_only:
            reason = "WEAK_VERSION_KEYWORD_ONLY"
        elif multi_version_unknown:
            reason = "MULTI_VERSION_UNKNOWN"
        else:
            reason = "MISSING_EXPLICIT_VERSION_STATUS"
        relations.append(
            VersionRelation(
                src_id=item.object_key,
                tgt_id=node.version_id,
                relation_type=REL_VERSION_REVIEW_REQUIRED,
                description=f"{item.object_key} requires version review.",
                source_id=item.source_text_unit_id,
                evidence_text=item.evidence_text,
                confidence_score=0.8,
                safe_to_auto_accept=False,
                requires_human_review=True,
                reason_code=reason,
                metadata=_version_metadata(
                    item,
                    relation_type=REL_VERSION_REVIEW_REQUIRED,
                    requires_human_review=True,
                    reason_code=reason,
                ),
            )
        )
    return relations


def _group_conflict_relations(
    group_items: list[VersionedSemanticObject],
    group_nodes: list[RuleVersionNode],
    *,
    policy: VersionRelationPolicy,
) -> list[VersionRelation]:
    relations: list[VersionRelation] = []
    for left_index, left in enumerate(group_items):
        for right_index in range(left_index + 1, len(group_items)):
            right = group_items[right_index]
            if not _has_rule_conflict(left.rule_text, right.rule_text, policy):
                continue
            left_node = group_nodes[left_index]
            right_node = group_nodes[right_index]
            relations.append(
                VersionRelation(
                    src_id=left_node.version_id,
                    tgt_id=right_node.version_id,
                    relation_type=REL_VERSION_CONFLICT,
                    description=f"{left.object_key} version evidence conflicts with another version.",
                    source_id=left.source_text_unit_id,
                    evidence_text=left.evidence_text,
                    confidence_score=0.75,
                    safe_to_auto_accept=False,
                    requires_human_review=True,
                    reason_code="CONFLICT_WITHOUT_SUPERSEDES",
                    metadata=_version_metadata(
                        left,
                        relation_type=REL_VERSION_CONFLICT,
                        requires_human_review=True,
                        reason_code="CONFLICT_WITHOUT_SUPERSEDES",
                        extra={"conflictTargetVersionId": right_node.version_id},
                    ),
                )
            )
            relations.append(
                VersionRelation(
                    src_id=left.object_key,
                    tgt_id=left_node.version_id,
                    relation_type=REL_VERSION_REVIEW_REQUIRED,
                    description=f"{left.object_key} requires review because version evidence conflicts.",
                    source_id=left.source_text_unit_id,
                    evidence_text=left.evidence_text,
                    confidence_score=0.75,
                    safe_to_auto_accept=False,
                    requires_human_review=True,
                    reason_code="CONFLICT_WITHOUT_SUPERSEDES",
                    metadata=_version_metadata(
                        left,
                        relation_type=REL_VERSION_REVIEW_REQUIRED,
                        requires_human_review=True,
                        reason_code="CONFLICT_WITHOUT_SUPERSEDES",
                    ),
                )
            )
    return relations


def _entity_from_version_node(node: RuleVersionNode) -> KgEntity:
    return KgEntity(
        entity_name=node.version_id,
        entity_type="RuleVersion",
        description=f"Rule version {node.version_label}",
        source_id=node.source_text_unit_id or "UNKNOWN",
        metadata=dict(node.metadata),
    )


def _relationship_from_version_relation(item: VersionRelation) -> KgRelationship:
    metadata = {
        **item.metadata,
        "relationType": item.relation_type,
        "evidenceText": item.evidence_text,
        "confidenceScore": item.confidence_score,
        "safeToAutoAccept": item.safe_to_auto_accept,
        "requiresHumanReview": item.requires_human_review,
        "reasonCode": item.reason_code,
        "knowledgeStatus": "ReviewRequired" if item.requires_human_review else "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": "VERSION_REVIEW" if item.requires_human_review else "AUTO_ACCEPT_FOR_REPORT",
    }
    return KgRelationship(
        src_id=item.src_id,
        tgt_id=item.tgt_id,
        description=item.description,
        keywords=item.relation_type,
        source_id=item.source_id or "UNKNOWN",
        weight=item.confidence_score,
        metadata=metadata,
    )


def _version_metadata(
    item: VersionedSemanticObject,
    *,
    relation_type: str | None,
    requires_human_review: bool,
    reason_code: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "documentId": item.raw.get("documentId"),
        "moduleCode": item.module_code,
        "domainCode": item.domain_code,
        "featureKey": item.feature_key,
        "objectType": item.object_type,
        "objectKey": item.object_key,
        "ruleDimension": item.rule_dimension,
        "version_group_key": item.version_group_key,
        "versionGroupKey": item.version_group_key,
        "sourceUsId": item.source_us_id,
        "sourceTextUnitId": item.source_text_unit_id,
        "textUnitId": item.source_text_unit_id,
        "sectionType": item.section_type,
        "sourceSpan": item.source_span,
        "textHash": item.text_hash,
        "evidenceText": item.evidence_text,
        "ruleText": item.rule_text,
        "ruleVersion": item.rule_version or f"source:{item.source_us_id or item.source_text_unit_id}",
        "latestFlag": item.latest_flag,
        "versionStatus": item.version_status or VERSION_STATUS_UNKNOWN,
        "supersedes": list(item.supersedes),
        "versionKeywords": list(item.version_keywords),
        "relationType": relation_type,
        "requiresHumanReview": requires_human_review,
        "safeToTestGraph": bool(item.raw.get("safeToTestGraph")) or not requires_human_review,
        "safeToFormalGraph": bool(item.raw.get("safeToFormalGraph")),
        "reasonCode": reason_code,
        "knowledgeStatus": "ReviewRequired" if requires_human_review else "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": "VERSION_REVIEW" if requires_human_review else "AUTO_ACCEPT_FOR_REPORT",
        "confidenceScore": 0.8,
        "graphWriteCalled": False,
        "formalGraphEnabled": False,
        **(extra or {}),
    }


def _rule_version_id(item: VersionedSemanticObject) -> str:
    seed = "|".join(
        [
            item.version_group_key,
            item.rule_version or "",
            item.source_us_id or "",
            item.source_text_unit_id or "",
            item.rule_text or "",
            item.text_hash or "",
        ]
    )
    return f"RuleVersion:{_stable_hash(seed)}"


def _version_group_key(
    *,
    module_code: str | None,
    domain_code: str | None,
    feature_key: str | None,
    object_type: str,
    object_key: str,
    rule_dimension: str | None,
) -> str:
    return "|".join(
        [
            _normalize_key(module_code),
            _normalize_key(domain_code),
            _normalize_key(feature_key),
            _normalize_key(object_type),
            _normalize_key(object_key),
            _normalize_key(rule_dimension),
        ]
    )


def _rule_dimension(object_type: str, metadata: dict[str, Any]) -> str:
    explicit = _string_or_none(metadata.get("ruleDimension"))
    if explicit:
        return explicit
    section = _string_or_none(metadata.get("sectionType"))
    if section:
        return section
    defaults = {
        "FieldSpec": "field_rule",
        "RuleAtom": "business_rule",
        "StateTransition": "status_value_rule",
        "TaskRule": "task_generation_rule",
        "MessageAtom": "message_rule",
        "RolePermission": "permission_rule",
        "IntegrationEndpoint": "api_mapping_rule",
        "ReportSpec": "report_filter_rule",
        "DataMigrationSpec": "migration_validation_rule",
        "DomainObject": "domain_object_rule",
    }
    return defaults.get(object_type, "semantic_object_rule")


def _has_rule_conflict(
    left: str | None,
    right: str | None,
    policy: VersionRelationPolicy,
) -> bool:
    left_text = str(left or "").lower()
    right_text = str(right or "").lower()
    if not left_text or not right_text or left_text == right_text:
        return False
    joined = (left_text, right_text)
    for positive, negative in policy.opposite_keyword_pairs:
        positive = positive.lower()
        negative = negative.lower()
        if (positive in joined[0] and negative in joined[1]) or (
            negative in joined[0] and positive in joined[1]
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


def _merge_entities(existing: list[KgEntity], additions: list[KgEntity]) -> list[KgEntity]:
    values: dict[str, KgEntity] = {item.entity_name: item for item in existing}
    for item in additions:
        values.setdefault(item.entity_name, item)
    return list(values.values())


def _merge_relationships(
    existing: list[KgRelationship],
    additions: list[KgRelationship],
) -> list[KgRelationship]:
    values: dict[tuple[str, str, str, str], KgRelationship] = {
        (item.src_id, item.tgt_id, item.keywords, item.source_id): item
        for item in existing
    }
    for item in additions:
        values.setdefault((item.src_id, item.tgt_id, item.keywords, item.source_id), item)
    return list(values.values())


def _dedupe_objects(objects: list[VersionedSemanticObject]) -> list[VersionedSemanticObject]:
    values: dict[tuple[str, str, str | None, str | None], VersionedSemanticObject] = {}
    for item in objects:
        values.setdefault(
            (
                item.version_group_key,
                item.object_key,
                item.source_text_unit_id,
                item.text_hash,
            ),
            item,
        )
    return list(values.values())


def _dedupe_relations(relations: list[VersionRelation]) -> list[VersionRelation]:
    values: dict[tuple[str, str, str, str | None], VersionRelation] = {}
    for item in relations:
        values.setdefault((item.src_id, item.tgt_id, item.relation_type, item.source_id), item)
    return list(values.values())


def _group_by_version_key(
    objects: list[VersionedSemanticObject],
) -> dict[str, list[VersionedSemanticObject]]:
    groups: dict[str, list[VersionedSemanticObject]] = defaultdict(list)
    for item in objects:
        groups[item.version_group_key].append(item)
    return dict(groups)


def _version_status(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    aliases = {
        "latest": "Current",
        "current": "Current",
        "active": "Current",
        "historical": "Historical",
        "deprecated": "Deprecated",
        "candidate": "Candidate",
        "reviewrequired": "ReviewRequired",
        "review_required": "ReviewRequired",
        "unknown": "Unknown",
    }
    return aliases.get(text.lower().replace(" ", ""), text)


def _version_keywords(metadata: dict[str, Any]) -> list[str]:
    keywords = metadata.get("versionKeywords") or metadata.get("keywords") or []
    if isinstance(keywords, str):
        return [keywords]
    if isinstance(keywords, list):
        return [str(item) for item in keywords if item not in (None, "")]
    return []


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_key(value: Any) -> str:
    return str(value or "NA").strip().lower()


def _stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _issue(code: str, object_key: str) -> dict[str, Any]:
    return {"code": code, "objectKey": object_key}


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = [
    "VERSIONED_ENTITY_TYPES",
    "VERSION_RULE_RELATIONS",
    "augment_kg_payload_with_version_relations",
    "build_lc_version_relation_coverage_report",
    "build_version_relations",
    "extract_versioned_semantic_objects",
    "serialize_version_coverage_report",
]
