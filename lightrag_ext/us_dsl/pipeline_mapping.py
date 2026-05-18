from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .payload_types import DslAwareIngestionPayload


PREVIEW_LIMIT = 300
SYNTHETIC_CONTEXT_MARKERS = (
    "<DSL_CONTEXT>",
    "</DSL_CONTEXT>",
    "<SOURCE_TEXT>",
    "</SOURCE_TEXT>",
)


@dataclass(frozen=True)
class PipelineMappingIssue:
    severity: str
    code: str
    message: str
    chunk_id: str | None = None


@dataclass(frozen=True)
class VectorStoreMappingItem:
    chunk_id: str
    target_text_chunks: bool
    target_chunks_vdb: bool
    content_source: str
    content_preview: str
    metadata: dict[str, Any]
    contamination_safe: bool


@dataclass(frozen=True)
class ExtractionMappingItem:
    chunk_id: str
    target_extract_entities: bool
    content_source: str
    content_preview: str
    parser_mode: str
    light_rag_mode: str
    metadata: dict[str, Any]
    dsl_context_present: bool
    source_text_present: bool
    future_target_extract_entities: bool = True


@dataclass(frozen=True)
class EvidenceMappingItem:
    text_unit_id: str
    vector_chunk_id: str
    extraction_chunk_id: str
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str
    source_span: dict[str, int]
    text_hash: str
    evidence_ready: bool


@dataclass
class PipelineMappingPlan:
    document_id: str
    dry_run: bool
    write_stores: bool
    call_extract_entities: bool
    modify_parser: bool
    modify_graph_merge: bool
    quality_gate_status: str
    recommended_next_step: str
    vector_store_mappings: list[VectorStoreMappingItem]
    extraction_mappings: list[ExtractionMappingItem]
    evidence_mappings: list[EvidenceMappingItem]
    summary: dict[str, Any]
    issues: list[PipelineMappingIssue] = field(default_factory=list)


def build_pipeline_mapping_plan(
    payload: DslAwareIngestionPayload,
    *,
    allow_warn: bool = True,
    require_quality_gate_not_fail: bool = True,
) -> PipelineMappingPlan:
    quality_gate = payload.summary.get("qualityGate", {})
    quality_metrics = payload.summary.get("qualityMetrics", {})
    quality_gate_status = str(quality_gate.get("status", "UNKNOWN"))
    blocked_by_quality = (
        require_quality_gate_not_fail and quality_gate_status == "FAIL"
    )
    safe_to_proceed = _safe_to_proceed_dry_run(quality_gate_status, allow_warn)
    if blocked_by_quality:
        safe_to_proceed = False

    vector_mappings = [_vector_mapping(item) for item in payload.vector_payload]
    extraction_mappings = [
        _extraction_mapping(item) for item in payload.extraction_payload
    ]
    evidence_mappings = [_evidence_mapping(item) for item in payload.metadata_payload]
    issues = _mapping_issues(vector_mappings, extraction_mappings, evidence_mappings)

    recommended_next_step = (
        "PIPELINE_MAPPING_DRY_RUN" if safe_to_proceed else "DO_NOT_HOOK"
    )
    summary = _summary(
        vector_mappings=vector_mappings,
        extraction_mappings=extraction_mappings,
        evidence_mappings=evidence_mappings,
        quality_gate_status=quality_gate_status,
        quality_metrics=quality_metrics,
        safe_to_proceed=safe_to_proceed,
    )

    return PipelineMappingPlan(
        document_id=payload.document_id,
        dry_run=True,
        write_stores=False,
        call_extract_entities=False,
        modify_parser=False,
        modify_graph_merge=False,
        quality_gate_status=quality_gate_status,
        recommended_next_step=recommended_next_step,
        vector_store_mappings=vector_mappings,
        extraction_mappings=extraction_mappings,
        evidence_mappings=evidence_mappings,
        summary=summary,
        issues=issues,
    )


def serialize_pipeline_mapping_plan(plan: PipelineMappingPlan) -> dict[str, Any]:
    return {
        "documentId": plan.document_id,
        "dryRun": plan.dry_run,
        "writeStores": plan.write_stores,
        "callExtractEntities": plan.call_extract_entities,
        "modifyParser": plan.modify_parser,
        "modifyGraphMerge": plan.modify_graph_merge,
        "qualityGateStatus": plan.quality_gate_status,
        "recommendedNextStep": plan.recommended_next_step,
        "summary": plan.summary,
        "vectorStoreMappings": [
            {
                "chunkId": item.chunk_id,
                "targetTextChunks": item.target_text_chunks,
                "targetChunksVdb": item.target_chunks_vdb,
                "contentSource": item.content_source,
                "contentPreview": item.content_preview,
                "metadata": item.metadata,
                "contaminationSafe": item.contamination_safe,
            }
            for item in plan.vector_store_mappings
        ],
        "extractionMappings": [
            {
                "chunkId": item.chunk_id,
                "targetExtractEntities": item.target_extract_entities,
                "futureTargetExtractEntities": item.future_target_extract_entities,
                "contentSource": item.content_source,
                "contentPreview": item.content_preview,
                "parserMode": item.parser_mode,
                "lightRagMode": item.light_rag_mode,
                "metadata": item.metadata,
                "dslContextPresent": item.dsl_context_present,
                "sourceTextPresent": item.source_text_present,
            }
            for item in plan.extraction_mappings
        ],
        "evidenceMappings": [
            {
                "textUnitId": item.text_unit_id,
                "vectorChunkId": item.vector_chunk_id,
                "extractionChunkId": item.extraction_chunk_id,
                "sourceUsId": item.source_us_id,
                "featureKey": item.feature_key,
                "domainCode": item.domain_code,
                "sectionType": item.section_type,
                "sourceSpan": item.source_span,
                "textHash": item.text_hash,
                "evidenceReady": item.evidence_ready,
            }
            for item in plan.evidence_mappings
        ],
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "chunkId": issue.chunk_id,
            }
            for issue in plan.issues
        ],
    }


def _vector_mapping(item) -> VectorStoreMappingItem:
    contamination_safe = not _contains_synthetic_context(item.content)
    return VectorStoreMappingItem(
        chunk_id=item.chunk_id,
        target_text_chunks=True,
        target_chunks_vdb=True,
        content_source="vector_payload.content",
        content_preview=_preview(item.content),
        metadata=item.metadata,
        contamination_safe=contamination_safe,
    )


def _extraction_mapping(item) -> ExtractionMappingItem:
    dsl_context_present = (
        "<DSL_CONTEXT>" in item.content and "</DSL_CONTEXT>" in item.content
    )
    source_text_present = (
        "<SOURCE_TEXT>" in item.content and "</SOURCE_TEXT>" in item.content
    )
    return ExtractionMappingItem(
        chunk_id=item.chunk_id,
        target_extract_entities=False,
        content_source="extraction_payload.content",
        content_preview=_preview(item.content),
        parser_mode=item.metadata.get("parserMode", "tuple_delimited"),
        light_rag_mode=item.metadata.get("lightRagMode", "tuple_prompt_context"),
        metadata=item.metadata,
        dsl_context_present=dsl_context_present,
        source_text_present=source_text_present,
    )


def _evidence_mapping(item) -> EvidenceMappingItem:
    evidence_ready = bool(item.text_unit_id and item.source_span and item.text_hash)
    return EvidenceMappingItem(
        text_unit_id=item.text_unit_id,
        vector_chunk_id=item.vector_chunk_id,
        extraction_chunk_id=item.extraction_chunk_id,
        source_us_id=item.source_us_id,
        feature_key=item.feature_key,
        domain_code=item.domain_code,
        section_type=item.section_type,
        source_span=item.source_span,
        text_hash=item.text_hash,
        evidence_ready=evidence_ready,
    )


def _mapping_issues(
    vector_mappings: list[VectorStoreMappingItem],
    extraction_mappings: list[ExtractionMappingItem],
    evidence_mappings: list[EvidenceMappingItem],
) -> list[PipelineMappingIssue]:
    issues: list[PipelineMappingIssue] = []
    for item in vector_mappings:
        if not item.contamination_safe:
            issues.append(
                PipelineMappingIssue(
                    severity="ERROR",
                    code="VECTOR_MAPPING_CONTAMINATION",
                    message="Vector mapping preview contains synthetic DSL/SOURCE markers.",
                    chunk_id=item.chunk_id,
                )
            )
    for item in extraction_mappings:
        if not item.dsl_context_present:
            issues.append(
                PipelineMappingIssue(
                    severity="ERROR",
                    code="EXTRACTION_MAPPING_MISSING_DSL_CONTEXT",
                    message="Extraction mapping is missing DSL_CONTEXT.",
                    chunk_id=item.chunk_id,
                )
            )
        if not item.source_text_present:
            issues.append(
                PipelineMappingIssue(
                    severity="ERROR",
                    code="EXTRACTION_MAPPING_MISSING_SOURCE_TEXT",
                    message="Extraction mapping is missing SOURCE_TEXT.",
                    chunk_id=item.chunk_id,
                )
            )
    for item in evidence_mappings:
        if not item.evidence_ready:
            issues.append(
                PipelineMappingIssue(
                    severity="WARN",
                    code="EVIDENCE_MAPPING_NOT_READY",
                    message="Evidence mapping lacks text_unit_id, source_span, or text_hash.",
                    chunk_id=item.text_unit_id,
                )
            )
    return issues


def _summary(
    vector_mappings: list[VectorStoreMappingItem],
    extraction_mappings: list[ExtractionMappingItem],
    evidence_mappings: list[EvidenceMappingItem],
    quality_gate_status: str,
    quality_metrics: dict[str, Any],
    safe_to_proceed: bool,
) -> dict[str, Any]:
    vector_contamination_count = sum(
        1 for item in vector_mappings if not item.contamination_safe
    )
    extraction_missing_dsl_context_count = sum(
        1 for item in extraction_mappings if not item.dsl_context_present
    )
    extraction_missing_source_text_count = sum(
        1 for item in extraction_mappings if not item.source_text_present
    )
    evidence_ready_count = sum(1 for item in evidence_mappings if item.evidence_ready)
    evidence_not_ready_count = len(evidence_mappings) - evidence_ready_count

    return {
        "vectorMappingCount": len(vector_mappings),
        "extractionMappingCount": len(extraction_mappings),
        "evidenceMappingCount": len(evidence_mappings),
        "vectorContaminationCount": vector_contamination_count,
        "extractionMissingDslContextCount": extraction_missing_dsl_context_count,
        "extractionMissingSourceTextCount": extraction_missing_source_text_count,
        "evidenceReadyCount": evidence_ready_count,
        "evidenceNotReadyCount": evidence_not_ready_count,
        "qualityGateStatus": quality_gate_status,
        "candidateWarnRatio": quality_metrics.get("candidateWarnRatio", 0.0),
        "unknownRatio": quality_metrics.get("unknownRatio", 0.0),
        "unmappedRatio": quality_metrics.get("unmappedRatio", 0.0),
        "writeStores": False,
        "callExtractEntities": False,
        "safeToProceedDryRun": safe_to_proceed
        and vector_contamination_count == 0
        and extraction_missing_dsl_context_count == 0
        and extraction_missing_source_text_count == 0,
        "safeToWriteStores": False,
        "safeToCallExtractEntities": False,
    }


def _safe_to_proceed_dry_run(quality_gate_status: str, allow_warn: bool) -> bool:
    if quality_gate_status == "PASS":
        return True
    if quality_gate_status == "WARN":
        return allow_warn
    return False


def _contains_synthetic_context(text: str) -> bool:
    return any(marker in text for marker in SYNTHETIC_CONTEXT_MARKERS)


def _preview(text: str) -> str:
    return text[:PREVIEW_LIMIT]
