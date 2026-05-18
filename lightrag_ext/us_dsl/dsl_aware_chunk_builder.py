from __future__ import annotations

import json
from typing import Any

from .dsl_types import (
    DslAwareChunk,
    DslAwareChunkBuildIssue,
    DslAwareChunkBuildResult,
    DslCompiledResult,
    OntologyConfig,
    SourceTextUnit,
)
from .ontology_loader import load_ontology
from .prompt_context_builder import build_prompt_context


INSTRUCTION = (
    "Extract only from allowedEntityTypes and allowedRelationTypes. Do not invent labels. "
    "Separate entityType and entityName. Preserve evidence. Keep LightRAG tuple-delimited "
    "output in phase 1."
)
MAX_KNOWN_OBJECTS = 32


def build_dsl_aware_chunks(
    source_text_units: list[SourceTextUnit],
    dsl_result: DslCompiledResult | dict[str, Any],
    ontology: OntologyConfig | None = None,
) -> DslAwareChunkBuildResult:
    raw = _dsl_raw(dsl_result)
    if ontology is None:
        ontology = load_ontology()

    index = _DslIndex(raw)
    chunks: list[DslAwareChunk] = []
    issues: list[DslAwareChunkBuildIssue] = []

    for unit in source_text_units:
        feature_key = _resolve_feature_key(unit, index)
        if feature_key is None:
            issues.append(
                DslAwareChunkBuildIssue(
                    severity="WARN",
                    code="DSL_MAPPING_MISSING",
                    message="No DSL feature mapping found for source text unit.",
                    text_unit_id=unit.text_unit_id,
                )
            )

        feature = index.feature_by_key.get(feature_key or "")
        domain_code = _resolve_domain_code(unit, feature_key, feature, index)
        if domain_code == "Other" and unit.domain_code is None:
            issues.append(
                DslAwareChunkBuildIssue(
                    severity="WARN",
                    code="DSL_DOMAIN_FALLBACK",
                    message="No domain mapping found; using Other candidate fallback.",
                    text_unit_id=unit.text_unit_id,
                    feature_key=feature_key,
                )
            )

        allowed_entity_types, allowed_relation_types = _allowed_types(
            feature_key=feature_key,
            domain_code=domain_code,
            index=index,
            ontology=ontology,
        )
        known_objects = _known_objects(
            feature_key=feature_key,
            domain_code=domain_code,
            source_us_id=unit.us_id,
            feature=feature,
            raw=raw,
        )

        dsl_context = {
            "domainCode": domain_code,
            "featureKey": feature_key,
            "primaryDomain": _string_or_none(feature.get("primaryDomain"))
            if feature
            else domain_code,
            "relatedDomains": _string_list(feature.get("relatedDomains"))
            if feature
            else [],
            "sectionType": unit.section_type,
            "sourceUsId": unit.us_id,
            "sourceTextUnitId": unit.text_unit_id,
            "latestFlag": _latest_flag(feature),
            "allowedEntityTypes": allowed_entity_types,
            "allowedRelationTypes": allowed_relation_types,
            "knownObjects": known_objects,
            "instruction": INSTRUCTION,
        }
        evidence = {
            "documentId": unit.document_id,
            "sourceUsId": unit.us_id,
            "textUnitId": unit.text_unit_id,
            "sectionType": unit.section_type,
            "sourceSpan": unit.source_span,
            "textHash": unit.text_hash,
        }
        metadata = {
            "sourceType": "DslAwareChunk",
            "dslVersion": str(raw.get("dslVersion", "")),
            "ontologyVersion": str(raw.get("ontologyVersion", "")),
            "synonymVersion": _synonym_version(raw),
            "knowledgeStatus": "Confirmed" if feature_key else "Candidate",
            "lightRagMode": "tuple_prompt_context",
        }
        extraction_content = build_prompt_context(dsl_context, unit.chunk_text)
        chunks.append(
            DslAwareChunk(
                chunk_id=unit.text_unit_id,
                source_text=unit.chunk_text,
                vector_content=unit.chunk_text,
                extraction_content=extraction_content,
                dsl_context=dsl_context,
                evidence=evidence,
                metadata=metadata,
            )
        )

    return DslAwareChunkBuildResult(chunks=chunks, issues=issues)


class _DslIndex:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.feature_by_key = {
            feature["featureKey"]: feature
            for feature in _dict_list(raw.get("featureCatalogIndex"))
            if isinstance(feature.get("featureKey"), str)
        }
        self.feature_by_us = self._index_features_by_us()
        self.plans_by_us = self._index_plans_by_us(raw)
        self.gleaning_by_feature = {
            block["featureKey"]: block
            for block in _dict_list(raw.get("gleaningInputBlocks"))
            if isinstance(block.get("featureKey"), str)
        }

    def _index_features_by_us(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for feature in self.feature_by_key.values():
            for source_us_id in _string_list(feature.get("sourceUsIds")):
                result.setdefault(source_us_id, feature)
        return result

    @staticmethod
    def _index_plans_by_us(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for plan in _dict_list(raw.get("sourceVectorizationPlan")):
            source_us_id = _string_or_none(plan.get("sourceUsId"))
            if source_us_id:
                result.setdefault(source_us_id, []).append(plan)
        return result


def _resolve_feature_key(unit: SourceTextUnit, index: _DslIndex) -> str | None:
    if unit.feature_key:
        return unit.feature_key

    for plan in index.plans_by_us.get(unit.us_id or "", []):
        feature_key = _string_or_none(plan.get("featureKey"))
        if feature_key:
            return feature_key

    feature = index.feature_by_us.get(unit.us_id or "")
    if feature:
        return _string_or_none(feature.get("featureKey"))
    return None


def _resolve_domain_code(
    unit: SourceTextUnit,
    feature_key: str | None,
    feature: dict[str, Any] | None,
    index: _DslIndex,
) -> str:
    if unit.domain_code:
        return unit.domain_code

    for plan in index.plans_by_us.get(unit.us_id or "", []):
        if feature_key and plan.get("featureKey") != feature_key:
            continue
        domain_code = _string_or_none(plan.get("domainCode"))
        if domain_code:
            return domain_code

    if feature:
        primary_domain = _string_or_none(feature.get("primaryDomain"))
        if primary_domain:
            return primary_domain

    return "Other"


def _allowed_types(
    feature_key: str | None,
    domain_code: str,
    index: _DslIndex,
    ontology: OntologyConfig,
) -> tuple[list[str], list[str]]:
    block = index.gleaning_by_feature.get(feature_key or "")
    entity_types = _string_list(block.get("allowedEntityTypes")) if block else []
    relation_types = _string_list(block.get("allowedRelationTypes")) if block else []

    if not entity_types:
        entity_types = sorted(ontology.allowed_entity_types(domain_code))
    if not relation_types:
        relation_types = sorted(ontology.allowed_relation_types(domain_code))

    return (
        _stable_unique([*entity_types, "CandidateEntity"]),
        _stable_unique([*relation_types, "CandidateRelation"]),
    )


def _known_objects(
    feature_key: str | None,
    domain_code: str,
    source_us_id: str | None,
    feature: dict[str, Any] | None,
    raw: dict[str, Any],
) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if feature_key and feature:
        objects.append(
            {
                "objectType": "FeatureCatalog",
                "entityType": "FeatureCatalog",
                "entityName": _feature_name(feature),
                "objectId": _string_or_none(feature.get("objectId")) or feature_key,
                "featureKey": feature_key,
                "domainCode": _string_or_none(feature.get("primaryDomain")) or domain_code,
                "knowledgeStatus": _string_or_none(feature.get("knowledgeStatus"))
                or "Confirmed",
            }
        )

    confirmed = raw.get("confirmedDslObjects")
    if not isinstance(confirmed, dict):
        return objects

    for collection_name in (
        "entities",
        "fieldSpecs",
        "ruleAtoms",
        "stateTransitions",
        "taskRules",
        "relations",
    ):
        for item in _dict_list(confirmed.get(collection_name)):
            if not _object_matches(item, feature_key, domain_code, source_us_id):
                continue
            compact = _compact_known_object(collection_name, item, feature_key, domain_code)
            if compact:
                objects.append(compact)
            if len(objects) >= MAX_KNOWN_OBJECTS:
                return objects

    return objects


def _object_matches(
    item: dict[str, Any],
    feature_key: str | None,
    domain_code: str,
    source_us_id: str | None,
) -> bool:
    item_feature_key = _string_or_none(item.get("featureKey"))
    if feature_key and item_feature_key == feature_key:
        return True

    item_source_us_id = _string_or_none(item.get("sourceUsId"))
    if source_us_id and item_source_us_id == source_us_id:
        return True

    if source_us_id and source_us_id in _string_list(item.get("sourceUsIds")):
        return True

    item_domain_code = _string_or_none(item.get("domainCode"))
    return bool(item_domain_code and item_domain_code == domain_code and item_feature_key is None)


def _compact_known_object(
    collection_name: str,
    item: dict[str, Any],
    feature_key: str | None,
    domain_code: str,
) -> dict[str, Any] | None:
    entity_name = _first_string(
        item,
        "entityName",
        "fieldName",
        "ruleName",
        "transitionName",
        "taskName",
        "relationName",
        "name",
    )
    object_id = _first_string(item, "objectId", "id", "entityId", "fieldId", "ruleId")
    entity_type = _string_or_none(item.get("entityType")) or _collection_entity_type(
        collection_name
    )
    relation_type = _string_or_none(item.get("relationType"))

    if entity_name is None and relation_type is None:
        return None

    result = {
        "objectType": collection_name,
        "entityType": entity_type,
        "entityName": entity_name,
        "objectId": object_id,
        "featureKey": _string_or_none(item.get("featureKey")) or feature_key,
        "domainCode": _string_or_none(item.get("domainCode")) or domain_code,
        "knowledgeStatus": _string_or_none(item.get("knowledgeStatus")) or "Confirmed",
    }
    if relation_type:
        result["relationType"] = relation_type
        result["sourceEntity"] = _string_or_none(item.get("sourceEntity"))
        result["targetEntity"] = _string_or_none(item.get("targetEntity"))

    return {key: value for key, value in result.items() if value is not None}


def _collection_entity_type(collection_name: str) -> str:
    return {
        "fieldSpecs": "FieldSpec",
        "ruleAtoms": "RuleAtom",
        "stateTransitions": "StateTransition",
        "taskRules": "TaskRule",
        "relations": "CandidateRelation",
    }.get(collection_name, "CandidateEntity")


def _feature_name(feature: dict[str, Any]) -> str:
    return (
        _first_string(feature, "featureName", "title", "name", "featureKey")
        or "FeatureCatalog"
    )


def _latest_flag(feature: dict[str, Any] | None) -> bool:
    if not feature:
        return True
    value = feature.get("latestFlag")
    return value if isinstance(value, bool) else True


def _synonym_version(raw: dict[str, Any]) -> str:
    term_normalization = raw.get("termNormalization")
    if isinstance(term_normalization, dict):
        value = term_normalization.get("synonymVersion")
        if value is not None:
            return str(value)
    return ""


def _dsl_raw(dsl_result: DslCompiledResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(dsl_result, DslCompiledResult):
        return dsl_result.raw
    return dsl_result


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _first_string(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            return value
    return None


def _stable_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def known_objects_json_size(dsl_context: dict[str, Any]) -> int:
    return len(
        json.dumps(
            dsl_context.get("knownObjects", []),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
