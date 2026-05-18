from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .ontology_loader import load_ontology
from .payload_types import DslAwareIngestionIssue, DslAwareIngestionPayload


SECTION_TYPES = [
    "us_header",
    "gwt",
    "business_rule",
    "field_table",
    "state_rule",
    "task_rule",
    "api_desc",
    "report_rule",
    "migration_rule",
    "dfx_rule",
    "acceptance_criteria",
    "ui_reference",
    "unknown",
]
MAPPING_STATUSES = ["MAPPED", "FALLBACK_OTHER", "MISSING_DSL_MAPPING"]
SYNTHETIC_CONTEXT_MARKERS = (
    "<DSL_CONTEXT>",
    "</DSL_CONTEXT>",
    "<SOURCE_TEXT>",
    "</SOURCE_TEXT>",
)


def apply_payload_quality_metrics(
    payload: DslAwareIngestionPayload,
    ontology=None,
) -> DslAwareIngestionPayload:
    if ontology is None:
        ontology = load_ontology()

    _append_quality_issues(payload)
    quality_metrics = build_quality_metrics(payload, ontology=ontology)
    quality_gate = build_quality_gate(quality_metrics)
    integration_readiness = build_integration_readiness(quality_gate)

    payload.summary["qualityMetrics"] = quality_metrics
    payload.summary["qualityGate"] = quality_gate
    payload.summary["integrationReadiness"] = integration_readiness
    payload.summary["unmappedRatio"] = quality_metrics["unmappedRatio"]
    payload.summary["sectionTypeDistribution"] = quality_metrics[
        "sectionTypeDistribution"
    ]
    return payload


def build_quality_metrics(
    payload: DslAwareIngestionPayload,
    ontology=None,
) -> dict[str, Any]:
    if ontology is None:
        ontology = load_ontology()

    issue_code_distribution = _issue_code_distribution(payload)
    candidate_entity_warn_count = issue_code_distribution.get("CANDIDATE_ENTITY", 0)
    candidate_relation_warn_count = issue_code_distribution.get("CANDIDATE_RELATION", 0)
    candidate_warn_count = candidate_entity_warn_count + candidate_relation_warn_count
    chunk_count = max(payload.dsl_aware_chunk_count, 1)

    mapping_distribution = _mapping_status_distribution(payload)
    section_distribution = _section_type_distribution(payload)
    active_domain_distribution = _active_domain_distribution(payload)
    payload_contamination = _payload_contamination(payload)
    payload_consistency = _payload_consistency(payload)
    active_ontology_size = _active_ontology_size(payload, ontology)
    known_objects_size = _known_objects_size(payload)
    error_issue_count = sum(1 for issue in payload.issues if issue.severity == "ERROR")
    warn_issue_count = sum(1 for issue in payload.issues if issue.severity == "WARN")
    unmapped_count = (
        mapping_distribution["FALLBACK_OTHER"]
        + mapping_distribution["MISSING_DSL_MAPPING"]
    )
    unknown_count = section_distribution.get("unknown", 0)
    metadata_count = max(len(payload.metadata_payload), 1)

    return {
        "candidateWarnCount": candidate_warn_count,
        "candidateWarnRatio": candidate_warn_count / chunk_count,
        "candidateEntityWarnCount": candidate_entity_warn_count,
        "candidateRelationWarnCount": candidate_relation_warn_count,
        "errorIssueCount": error_issue_count,
        "warnIssueCount": warn_issue_count,
        "issueCodeDistribution": issue_code_distribution,
        "mappingStatusDistribution": mapping_distribution,
        "sectionTypeDistribution": section_distribution,
        "activeDomainDistribution": active_domain_distribution,
        "activeOntologySize": active_ontology_size,
        "knownObjectsSize": known_objects_size,
        "payloadContamination": payload_contamination,
        "payloadConsistency": payload_consistency,
        "formalStoreReadiness": {
            "confirmedOnlyForFormalStore": True,
            "candidateRequiresPromotion": True,
            "safeForDirectFormalGraphWrite": False,
            "safeForDryRun": True,
        },
        "unmappedCount": unmapped_count,
        "unmappedRatio": unmapped_count / metadata_count,
        "unknownCount": unknown_count,
        "unknownRatio": unknown_count / metadata_count,
    }


def build_quality_gate(quality_metrics: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    payload_contamination = quality_metrics["payloadContamination"]
    payload_consistency = quality_metrics["payloadConsistency"]

    fail_conditions = [
        (quality_metrics["errorIssueCount"] > 0, "error issues exist"),
        (
            payload_contamination["vectorPayloadContainsDslContext"],
            "vector payload contains DSL_CONTEXT",
        ),
        (
            payload_contamination["extractionPayloadMissingDslContextCount"] > 0,
            "extraction payload missing DSL_CONTEXT",
        ),
        (
            not payload_consistency["allVectorContentEqualsSourceText"],
            "vector content does not equal source text",
        ),
        (
            not payload_consistency["vectorPayloadCountEqualsDslAwareChunkCount"],
            "vector payload count mismatch",
        ),
        (
            not payload_consistency["extractionPayloadCountEqualsDslAwareChunkCount"],
            "extraction payload count mismatch",
        ),
        (
            not payload_consistency["metadataPayloadCountEqualsDslAwareChunkCount"],
            "metadata payload count mismatch",
        ),
    ]
    for condition, reason in fail_conditions:
        if condition:
            reasons.append(reason)
    if reasons:
        return {"status": "FAIL", "reasons": reasons}

    warn_high_conditions = [
        (quality_metrics["candidateWarnRatio"] > 0.70, "candidate warn ratio > 0.70"),
        (quality_metrics["unmappedRatio"] > 0.30, "unmapped ratio > 0.30"),
        (quality_metrics["unknownRatio"] > 0.30, "unknown section ratio > 0.30"),
        (
            not quality_metrics["activeOntologySize"]["activeOntologyOnlyLikely"],
            "active ontology looks like full ontology",
        ),
        (
            quality_metrics["knownObjectsSize"]["maxKnownObjectsSerializedLength"]
            > 20000,
            "knownObjects serialized length > 20000",
        ),
    ]
    for condition, reason in warn_high_conditions:
        if condition:
            reasons.append(reason)
    if reasons:
        return {"status": "WARN_HIGH", "reasons": reasons}

    warn_conditions = [
        (quality_metrics["candidateWarnRatio"] > 0.30, "candidate warn ratio > 0.30"),
        (quality_metrics["candidateWarnCount"] > 0, "candidate warnings exist"),
        (quality_metrics["unmappedRatio"] > 0.10, "unmapped ratio > 0.10"),
        (quality_metrics["unknownRatio"] > 0.15, "unknown section ratio > 0.15"),
        (
            quality_metrics["knownObjectsSize"]["maxKnownObjectsSerializedLength"] > 8000,
            "knownObjects serialized length > 8000",
        ),
    ]
    for condition, reason in warn_conditions:
        if condition:
            reasons.append(reason)
    if reasons:
        return {"status": "WARN", "reasons": reasons}

    return {"status": "PASS", "reasons": []}


def build_integration_readiness(quality_gate: dict[str, Any]) -> dict[str, Any]:
    status = quality_gate["status"]
    return {
        "recommendedNextStep": "DO_NOT_HOOK"
        if status == "FAIL"
        else "PIPELINE_HOOK_DRY_RUN",
        "requiresFeatureFlag": True,
        "featureFlagName": "enable_dsl_aware_ingestion",
        "defaultEnabled": False,
        "supportsDryRun": True,
        "supportsFallbackToOriginalPipeline": True,
        "recommendedFallback": "original_lightrag_pipeline",
        "doNotModifyParser": True,
        "doNotModifyGraphMerge": True,
        "doNotWriteStoresInAdapter": True,
    }


def _append_quality_issues(payload: DslAwareIngestionPayload) -> None:
    contamination = _payload_contamination(payload)
    consistency = _payload_consistency(payload)
    missing_mapping_count = sum(
        1
        for item in payload.metadata_payload
        if item.mapping_status == "MISSING_DSL_MAPPING"
    )

    if contamination["vectorPayloadContainsDslContext"]:
        _append_issue_once(
            payload,
            code="VECTOR_PAYLOAD_CONTAMINATION",
            severity="ERROR",
            message="Vector payload contains DSL_CONTEXT marker.",
        )
    if contamination["vectorPayloadContainsSyntheticSourceTextTag"]:
        _append_issue_once(
            payload,
            code="VECTOR_PAYLOAD_SYNTHETIC_SOURCE_TEXT_TAG",
            severity="ERROR",
            message="Vector payload contains synthetic SOURCE_TEXT marker.",
        )
    if contamination["extractionPayloadMissingDslContextCount"] > 0:
        _append_issue_once(
            payload,
            code="EXTRACTION_PAYLOAD_MISSING_CONTEXT",
            severity="ERROR",
            message="One or more extraction payload items are missing DSL_CONTEXT.",
        )
    if contamination["extractionPayloadMissingSourceTextCount"] > 0:
        _append_issue_once(
            payload,
            code="EXTRACTION_PAYLOAD_MISSING_SOURCE_TEXT",
            severity="ERROR",
            message="One or more extraction payload items are missing SOURCE_TEXT.",
        )
    if not consistency["allVectorContentEqualsSourceText"]:
        _append_issue_once(
            payload,
            code="VECTOR_CONTENT_NOT_SOURCE_TEXT",
            severity="ERROR",
            message="One or more vector payload items do not equal SOURCE_TEXT.",
        )
    if not all(
        [
            consistency["vectorPayloadCountEqualsDslAwareChunkCount"],
            consistency["extractionPayloadCountEqualsDslAwareChunkCount"],
            consistency["metadataPayloadCountEqualsDslAwareChunkCount"],
        ]
    ):
        _append_issue_once(
            payload,
            code="PAYLOAD_COUNT_MISMATCH",
            severity="ERROR",
            message="Payload item counts do not match dslAwareChunkCount.",
        )
    if missing_mapping_count > 0:
        _append_issue_once(
            payload,
            code="DSL_MAPPING_MISSING",
            severity="WARN",
            message="One or more metadata payload items have MISSING_DSL_MAPPING.",
        )


def _issue_code_distribution(payload: DslAwareIngestionPayload) -> dict[str, int]:
    return dict(sorted(Counter(issue.code for issue in payload.issues).items()))


def _mapping_status_distribution(payload: DslAwareIngestionPayload) -> dict[str, int]:
    counter = Counter(item.mapping_status for item in payload.metadata_payload)
    return {status: counter.get(status, 0) for status in MAPPING_STATUSES}


def _section_type_distribution(payload: DslAwareIngestionPayload) -> dict[str, int]:
    counter = Counter(item.section_type for item in payload.metadata_payload)
    result = {section_type: counter.get(section_type, 0) for section_type in SECTION_TYPES}
    for section_type, count in sorted(counter.items()):
        if section_type not in result:
            result[section_type] = count
    return result


def _active_domain_distribution(payload: DslAwareIngestionPayload) -> dict[str, int]:
    counter = Counter(
        item.domain_code for item in payload.metadata_payload if item.domain_code
    )
    return dict(sorted(counter.items()))


def _active_ontology_size(
    payload: DslAwareIngestionPayload,
    ontology,
) -> dict[str, Any]:
    entity_lengths = [
        len(item.metadata.get("allowedEntityTypes", []))
        for item in payload.extraction_payload
    ]
    relation_lengths = [
        len(item.metadata.get("allowedRelationTypes", []))
        for item in payload.extraction_payload
    ]
    total_entity_types = len(_full_entity_types(ontology))
    total_relation_types = len(_full_relation_types(ontology))
    max_entity = max(entity_lengths, default=0)
    max_relation = max(relation_lengths, default=0)
    active_ontology_only_likely = True
    if total_entity_types and max_entity > total_entity_types * 0.8:
        active_ontology_only_likely = False
    if total_relation_types and max_relation > total_relation_types * 0.8:
        active_ontology_only_likely = False

    return {
        "minAllowedEntityTypes": min(entity_lengths, default=0),
        "maxAllowedEntityTypes": max_entity,
        "avgAllowedEntityTypes": _avg(entity_lengths),
        "minAllowedRelationTypes": min(relation_lengths, default=0),
        "maxAllowedRelationTypes": max_relation,
        "avgAllowedRelationTypes": _avg(relation_lengths),
        "activeOntologyOnlyLikely": active_ontology_only_likely,
    }


def _known_objects_size(payload: DslAwareIngestionPayload) -> dict[str, Any]:
    counts = []
    lengths = []
    for item in payload.extraction_payload:
        known_objects = item.metadata.get("knownObjects", [])
        counts.append(len(known_objects) if isinstance(known_objects, list) else 0)
        lengths.append(
            len(json.dumps(known_objects, ensure_ascii=False, separators=(",", ":")))
        )
    return {
        "maxKnownObjectsCount": max(counts, default=0),
        "avgKnownObjectsCount": _avg(counts),
        "maxKnownObjectsSerializedLength": max(lengths, default=0),
        "avgKnownObjectsSerializedLength": _avg(lengths),
    }


def _payload_contamination(payload: DslAwareIngestionPayload) -> dict[str, Any]:
    vector_contains_dsl_context = any(
        "<DSL_CONTEXT>" in item.content or "</DSL_CONTEXT>" in item.content
        for item in payload.vector_payload
    )
    vector_contains_source_text_tag = any(
        "<SOURCE_TEXT>" in item.content or "</SOURCE_TEXT>" in item.content
        for item in payload.vector_payload
    )
    extraction_missing_dsl_context = sum(
        1
        for item in payload.extraction_payload
        if "<DSL_CONTEXT>" not in item.content or "</DSL_CONTEXT>" not in item.content
    )
    extraction_missing_source_text = sum(
        1
        for item in payload.extraction_payload
        if "<SOURCE_TEXT>" not in item.content or "</SOURCE_TEXT>" not in item.content
    )
    return {
        "vectorPayloadContainsDslContext": vector_contains_dsl_context,
        "vectorPayloadContainsSyntheticSourceTextTag": vector_contains_source_text_tag,
        "extractionPayloadMissingDslContextCount": extraction_missing_dsl_context,
        "extractionPayloadMissingSourceTextCount": extraction_missing_source_text,
    }


def _payload_consistency(payload: DslAwareIngestionPayload) -> dict[str, bool]:
    vector_by_chunk = {item.chunk_id: item for item in payload.vector_payload}
    extraction_by_source_chunk = {
        item.metadata.get("sourceChunkId"): item for item in payload.extraction_payload
    }
    all_vector_equals_source = True
    for chunk_id, vector_item in vector_by_chunk.items():
        extraction_item = extraction_by_source_chunk.get(chunk_id)
        source_text = (
            _extract_source_text(extraction_item.content) if extraction_item else None
        )
        if source_text is None or vector_item.content != source_text:
            all_vector_equals_source = False
            break

    return {
        "vectorPayloadCountEqualsDslAwareChunkCount": len(payload.vector_payload)
        == payload.dsl_aware_chunk_count,
        "extractionPayloadCountEqualsDslAwareChunkCount": len(payload.extraction_payload)
        == payload.dsl_aware_chunk_count,
        "metadataPayloadCountEqualsDslAwareChunkCount": len(payload.metadata_payload)
        == payload.dsl_aware_chunk_count,
        "allVectorContentEqualsSourceText": all_vector_equals_source,
        "allExtractionContentHasDslContext": all(
            "<DSL_CONTEXT>" in item.content and "</DSL_CONTEXT>" in item.content
            for item in payload.extraction_payload
        ),
    }


def _extract_source_text(content: str) -> str | None:
    start_marker = "<SOURCE_TEXT>\n"
    end_marker = "\n</SOURCE_TEXT>"
    if start_marker not in content or end_marker not in content:
        return None
    return content.split(start_marker, 1)[1].rsplit(end_marker, 1)[0]


def _append_issue_once(
    payload: DslAwareIngestionPayload,
    code: str,
    severity: str,
    message: str,
) -> None:
    if any(issue.code == code and issue.severity == severity for issue in payload.issues):
        return
    payload.issues.append(
        DslAwareIngestionIssue(severity=severity, code=code, message=message)
    )


def _full_entity_types(ontology) -> set[str]:
    result = set(ontology.entity_types.get("Common", set()))
    for values in ontology.entity_types.values():
        result.update(values)
    result.add("CandidateEntity")
    return result


def _full_relation_types(ontology) -> set[str]:
    result = set(ontology.relation_types.get("Common", set()))
    for values in ontology.relation_types.values():
        result.update(values)
    result.add("CandidateRelation")
    return result


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0
