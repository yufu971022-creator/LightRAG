from __future__ import annotations

from pathlib import Path
from typing import Any

from .dsl_aware_chunk_builder import build_dsl_aware_chunks
from .dsl_loader import load_dsl_compiled
from .dsl_types import DslCompiledResult, DslValidationError, OntologyConfig
from .dsl_validator import validate_dsl_compiled
from .ontology_loader import load_ontology
from .payload_types import (
    DslAwareIngestionIssue,
    DslAwareIngestionPayload,
    ExtractionPayloadItem,
    MetadataPayloadItem,
    VectorPayloadItem,
)
from .payload_quality import apply_payload_quality_metrics
from .source_text_unit_builder import build_source_text_units


LIGHTRAG_MODE = "tuple_prompt_context"
PARSER_MODE = "tuple_delimited"
SYNTHETIC_CONTEXT_MARKERS = (
    "<DSL_CONTEXT>",
    "</DSL_CONTEXT>",
    "<SOURCE_TEXT>",
    "</SOURCE_TEXT>",
)


def build_dsl_aware_ingestion_payload(
    content: str,
    document_id: str,
    dsl_path: str | Path | None = None,
    dsl_result: DslCompiledResult | dict[str, Any] | None = None,
    ontology: OntologyConfig | None = None,
    file_path: str | None = None,
    validate_dsl: bool = True,
) -> DslAwareIngestionPayload:
    if ontology is None:
        ontology = load_ontology()
    if ontology is None:
        raise ValueError("Ontology config is required")

    loaded_dsl = _load_or_validate_dsl(
        dsl_path=dsl_path,
        dsl_result=dsl_result,
        ontology=ontology,
        validate_dsl=validate_dsl,
    )
    raw = _dsl_raw(loaded_dsl)
    issues = _issues_from_dsl_result(loaded_dsl)

    source_units = build_source_text_units(
        content,
        document_id,
        dsl_result=loaded_dsl,
        file_path=file_path,
    )
    chunk_result = build_dsl_aware_chunks(source_units, loaded_dsl, ontology)
    issues.extend(_issues_from_chunk_result(chunk_result.issues))

    source_units_by_id = {unit.text_unit_id: unit for unit in source_units}
    vector_payload: list[VectorPayloadItem] = []
    extraction_payload: list[ExtractionPayloadItem] = []
    metadata_payload: list[MetadataPayloadItem] = []

    for chunk in chunk_result.chunks:
        source_unit = source_units_by_id.get(chunk.chunk_id)
        extraction_chunk_id = f"{chunk.chunk_id}:extract"
        mapping_status = _mapping_status(chunk.dsl_context)
        vector_metadata = _vector_metadata(
            chunk=chunk,
            file_path=file_path,
            dsl_version=str(raw.get("dslVersion", "")),
        )
        extraction_metadata = _extraction_metadata(chunk, extraction_chunk_id)

        issues.extend(_validate_vector_content(chunk))
        issues.extend(_validate_extraction_content(chunk, extraction_chunk_id))

        vector_payload.append(
            VectorPayloadItem(
                chunk_id=chunk.chunk_id,
                content=chunk.vector_content,
                metadata=vector_metadata,
            )
        )
        extraction_payload.append(
            ExtractionPayloadItem(
                chunk_id=extraction_chunk_id,
                content=chunk.extraction_content,
                metadata=extraction_metadata,
            )
        )
        metadata_payload.append(
            MetadataPayloadItem(
                text_unit_id=chunk.evidence.get("textUnitId", chunk.chunk_id),
                document_id=chunk.evidence.get("documentId", document_id),
                source_us_id=chunk.evidence.get("sourceUsId"),
                feature_key=chunk.dsl_context.get("featureKey"),
                domain_code=chunk.dsl_context.get("domainCode"),
                section_type=chunk.evidence.get("sectionType", ""),
                source_span=chunk.evidence.get("sourceSpan", {}),
                text_hash=chunk.evidence.get("textHash", ""),
                vector_chunk_id=chunk.chunk_id,
                extraction_chunk_id=extraction_chunk_id,
                knowledge_status=chunk.metadata.get("knowledgeStatus", "Candidate"),
                mapping_status=mapping_status,
            )
        )

        if source_unit is None:
            issues.append(
                DslAwareIngestionIssue(
                    severity="WARN",
                    code="SOURCE_TEXT_UNIT_NOT_FOUND",
                    message="Chunk has no matching SourceTextUnit by chunk_id.",
                    text_unit_id=chunk.chunk_id,
                    feature_key=chunk.dsl_context.get("featureKey"),
                    source_us_id=chunk.dsl_context.get("sourceUsId"),
                )
            )

    summary = _summary(
        document_id=document_id,
        raw=raw,
        source_units=source_units,
        chunks=chunk_result.chunks,
        vector_payload=vector_payload,
        extraction_payload=extraction_payload,
        metadata_payload=metadata_payload,
    )

    payload = DslAwareIngestionPayload(
        document_id=document_id,
        dsl_version=str(raw.get("dslVersion", "")),
        source_text_unit_count=len(source_units),
        dsl_aware_chunk_count=len(chunk_result.chunks),
        vector_payload=vector_payload,
        extraction_payload=extraction_payload,
        metadata_payload=metadata_payload,
        issues=issues,
        summary=summary,
    )
    return apply_payload_quality_metrics(payload, ontology=ontology)


def serialize_ingestion_payload(
    payload: DslAwareIngestionPayload,
    include_content: bool = True,
) -> dict[str, Any]:
    return {
        "documentId": payload.document_id,
        "dslVersion": payload.dsl_version,
        "summary": payload.summary,
        "vectorPayload": [
            _serialize_vector_item(item, include_content) for item in payload.vector_payload
        ],
        "extractionPayload": [
            _serialize_extraction_item(item, include_content)
            for item in payload.extraction_payload
        ],
        "metadataPayload": [
            {
                "textUnitId": item.text_unit_id,
                "documentId": item.document_id,
                "sourceUsId": item.source_us_id,
                "featureKey": item.feature_key,
                "domainCode": item.domain_code,
                "sectionType": item.section_type,
                "sourceSpan": item.source_span,
                "textHash": item.text_hash,
                "vectorChunkId": item.vector_chunk_id,
                "extractionChunkId": item.extraction_chunk_id,
                "knowledgeStatus": item.knowledge_status,
                "mappingStatus": item.mapping_status,
            }
            for item in payload.metadata_payload
        ],
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "textUnitId": issue.text_unit_id,
                "featureKey": issue.feature_key,
                "sourceUsId": issue.source_us_id,
            }
            for issue in payload.issues
        ],
    }


def _load_or_validate_dsl(
    dsl_path: str | Path | None,
    dsl_result: DslCompiledResult | dict[str, Any] | None,
    ontology: OntologyConfig,
    validate_dsl: bool,
) -> DslCompiledResult | dict[str, Any]:
    if dsl_result is not None:
        if validate_dsl:
            validation = validate_dsl_compiled(_dsl_raw(dsl_result), ontology)
            if validation.errors:
                raise DslValidationError("<dsl_result>", validation.issues)
            if isinstance(dsl_result, DslCompiledResult):
                dsl_result.issues.extend(validation.issues)
            else:
                return DslCompiledResult(
                    raw=dsl_result,
                    dsl_version=str(dsl_result.get("dslVersion", "")),
                    active_domains=_extract_active_domains(dsl_result),
                    feature_catalog_index=_dict_list(
                        dsl_result.get("featureCatalogIndex")
                    ),
                    source_vectorization_plan=_dict_list(
                        dsl_result.get("sourceVectorizationPlan")
                    ),
                    gleaning_input_blocks=_dict_list(
                        dsl_result.get("gleaningInputBlocks")
                    ),
                    issues=validation.issues,
                )
        return dsl_result

    if dsl_path is None:
        raise ValueError("Either dsl_path or dsl_result is required")
    return load_dsl_compiled(dsl_path, ontology=ontology, validate=validate_dsl)


def _vector_metadata(
    chunk,
    file_path: str | None,
    dsl_version: str,
) -> dict[str, Any]:
    return {
        "documentId": chunk.evidence.get("documentId"),
        "sourceUsId": chunk.evidence.get("sourceUsId"),
        "textUnitId": chunk.evidence.get("textUnitId"),
        "featureKey": chunk.dsl_context.get("featureKey"),
        "domainCode": chunk.dsl_context.get("domainCode"),
        "sectionType": chunk.evidence.get("sectionType"),
        "sourceSpan": chunk.evidence.get("sourceSpan"),
        "textHash": chunk.evidence.get("textHash"),
        "dslVersion": dsl_version,
        "latestFlag": chunk.dsl_context.get("latestFlag"),
        "filePath": file_path,
    }


def _extraction_metadata(chunk, extraction_chunk_id: str) -> dict[str, Any]:
    return {
        "documentId": chunk.evidence.get("documentId"),
        "sourceUsId": chunk.evidence.get("sourceUsId"),
        "textUnitId": chunk.evidence.get("textUnitId"),
        "featureKey": chunk.dsl_context.get("featureKey"),
        "domainCode": chunk.dsl_context.get("domainCode"),
        "sectionType": chunk.evidence.get("sectionType"),
        "sourceSpan": chunk.evidence.get("sourceSpan"),
        "textHash": chunk.evidence.get("textHash"),
        "lightRagMode": LIGHTRAG_MODE,
        "parserMode": PARSER_MODE,
        "sourceChunkId": chunk.chunk_id,
        "extractionChunkId": extraction_chunk_id,
        "allowedEntityTypes": chunk.dsl_context.get("allowedEntityTypes", []),
        "allowedRelationTypes": chunk.dsl_context.get("allowedRelationTypes", []),
        "knownObjects": chunk.dsl_context.get("knownObjects", []),
        "primaryDomain": chunk.dsl_context.get("primaryDomain"),
        "relatedDomains": chunk.dsl_context.get("relatedDomains", []),
        "latestFlag": chunk.dsl_context.get("latestFlag"),
    }


def _validate_vector_content(chunk) -> list[DslAwareIngestionIssue]:
    issues: list[DslAwareIngestionIssue] = []
    if chunk.vector_content != chunk.source_text:
        issues.append(
            _error(
                "VECTOR_CONTENT_NOT_SOURCE_TEXT",
                "Vector content must equal source_text.",
                chunk,
            )
        )
    for marker in SYNTHETIC_CONTEXT_MARKERS:
        if marker in chunk.vector_content:
            issues.append(
                _error(
                    "VECTOR_PAYLOAD_CONTAINS_SYNTHETIC_CONTEXT",
                    f"Vector content contains synthetic marker {marker}.",
                    chunk,
                )
            )
    return issues


def _validate_extraction_content(chunk, extraction_chunk_id: str):
    required_markers = (
        "<DSL_CONTEXT>",
        "</DSL_CONTEXT>",
        "<SOURCE_TEXT>",
        "</SOURCE_TEXT>",
        "domainCode",
        "featureKey",
        "allowedEntityTypes",
        "allowedRelationTypes",
    )
    issues: list[DslAwareIngestionIssue] = []
    for marker in required_markers:
        if marker not in chunk.extraction_content:
            issues.append(
                DslAwareIngestionIssue(
                    severity="ERROR",
                    code="EXTRACTION_PAYLOAD_MISSING_DSL_CONTEXT",
                    message=f"Extraction payload {extraction_chunk_id} misses {marker}.",
                    text_unit_id=chunk.evidence.get("textUnitId"),
                    feature_key=chunk.dsl_context.get("featureKey"),
                    source_us_id=chunk.dsl_context.get("sourceUsId"),
                )
            )
    return issues


def _summary(
    document_id: str,
    raw: dict[str, Any],
    source_units,
    chunks,
    vector_payload: list[VectorPayloadItem],
    extraction_payload: list[ExtractionPayloadItem],
    metadata_payload: list[MetadataPayloadItem],
) -> dict[str, Any]:
    unmapped_count = sum(
        1 for chunk in chunks if _mapping_status(chunk.dsl_context) != "MAPPED"
    )
    return {
        "documentId": document_id,
        "dslVersion": str(raw.get("dslVersion", "")),
        "sourceTextUnitCount": len(source_units),
        "dslAwareChunkCount": len(chunks),
        "vectorPayloadCount": len(vector_payload),
        "extractionPayloadCount": len(extraction_payload),
        "metadataPayloadCount": len(metadata_payload),
        "activeDomains": _extract_active_domains(raw),
        "sectionTypeDistribution": _section_distribution_from_units(source_units),
        "unmappedCount": unmapped_count,
        "unmappedRatio": unmapped_count / len(chunks) if chunks else 0.0,
        "vectorContentIsSourceText": all(
            chunk.vector_content == chunk.source_text for chunk in chunks
        ),
        "extractionContentHasDslContext": all(
            "<DSL_CONTEXT>" in chunk.extraction_content
            and "<SOURCE_TEXT>" in chunk.extraction_content
            for chunk in chunks
        ),
        "lightRagMode": LIGHTRAG_MODE,
        "parserMode": PARSER_MODE,
        "writeStores": False,
    }


def _section_distribution_from_units(source_units) -> dict[str, int]:
    result: dict[str, int] = {}
    for unit in source_units:
        result[unit.section_type] = result.get(unit.section_type, 0) + 1
    return dict(sorted(result.items()))


def _mapping_status(dsl_context: dict[str, Any]) -> str:
    if dsl_context.get("featureKey") is None:
        return "MISSING_DSL_MAPPING"
    if dsl_context.get("domainCode") == "Other":
        return "FALLBACK_OTHER"
    return "MAPPED"


def _issues_from_dsl_result(
    dsl_result: DslCompiledResult | dict[str, Any],
) -> list[DslAwareIngestionIssue]:
    if not isinstance(dsl_result, DslCompiledResult):
        return []
    return [
        DslAwareIngestionIssue(
            severity=issue.severity,
            code=issue.code,
            message=issue.message,
        )
        for issue in dsl_result.issues
    ]


def _issues_from_chunk_result(issues) -> list[DslAwareIngestionIssue]:
    return [
        DslAwareIngestionIssue(
            severity=issue.severity,
            code=issue.code,
            message=issue.message,
            text_unit_id=issue.text_unit_id,
            feature_key=issue.feature_key,
        )
        for issue in issues
    ]


def _error(code: str, message: str, chunk) -> DslAwareIngestionIssue:
    return DslAwareIngestionIssue(
        severity="ERROR",
        code=code,
        message=message,
        text_unit_id=chunk.evidence.get("textUnitId"),
        feature_key=chunk.dsl_context.get("featureKey"),
        source_us_id=chunk.dsl_context.get("sourceUsId"),
    )


def _serialize_vector_item(
    item: VectorPayloadItem,
    include_content: bool,
) -> dict[str, Any]:
    result = {"chunkId": item.chunk_id, "metadata": item.metadata}
    if include_content:
        result["content"] = item.content
    return result


def _serialize_extraction_item(
    item: ExtractionPayloadItem,
    include_content: bool,
) -> dict[str, Any]:
    result = {"chunkId": item.chunk_id, "metadata": item.metadata}
    if include_content:
        result["content"] = item.content
    return result


def _dsl_raw(dsl_result: DslCompiledResult | dict[str, Any]) -> dict[str, Any]:
    if isinstance(dsl_result, DslCompiledResult):
        return dsl_result.raw
    return dsl_result


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _extract_active_domains(raw: dict[str, Any]) -> list[str]:
    run_summary = raw.get("runSummary")
    if not isinstance(run_summary, dict):
        return []
    active_domains = run_summary.get("activeDomains")
    if not isinstance(active_domains, list):
        return []

    result = []
    for item in active_domains:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and isinstance(item.get("domainCode"), str):
            result.append(item["domainCode"])
    return result
