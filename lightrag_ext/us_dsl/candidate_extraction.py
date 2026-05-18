from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .candidate_quality import (
    validate_candidate_entity,
    validate_candidate_relation,
)
from .candidate_store import CandidateStore
from .candidate_types import (
    CandidateEntity,
    CandidateExtractionIssue,
    CandidateRelation,
    VALIDATION_INVALID_TYPE,
    VALIDATION_MISSING_EVIDENCE,
    VALIDATION_REVIEW_REQUIRED,
    VALIDATION_VALID,
)
from .extract_entities_dry_run import (
    ExtractEntitiesDryRunConfig,
    ExtractEntitiesDryRunReport,
    run_extract_entities_dry_run_from_payload,
)
from .payload_types import DslAwareIngestionPayload


ENABLE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_CANDIDATE_WRITE"
MAX_SAMPLES_ENV = "LIGHTRAG_DSL_CANDIDATE_WRITE_MAX_SAMPLES"
LIVE_LLM_ENV = "LIGHTRAG_DSL_CANDIDATE_WRITE_LIVE_LLM"
GLEANING_ENV = "LIGHTRAG_DSL_CANDIDATE_WRITE_GLEANING"
DEFAULT_MAX_SAMPLES = 6
HARD_MAX_SAMPLES = 10


@dataclass(frozen=True)
class CandidateExtractionWriteConfig:
    enabled: bool = False
    dry_run: bool = True
    candidate_only: bool = True
    write_candidate_store: bool = True
    write_graph: bool = False
    call_merge: bool = False
    call_extract_entities: bool = True
    use_native_extract_entities: bool = True
    use_fake_llm: bool = True
    run_live_llm: bool = False
    max_samples: int = DEFAULT_MAX_SAMPLES
    hard_max_samples: int = HARD_MAX_SAMPLES
    run_gleaning: bool = False
    max_gleaning_samples: int = 2
    require_quality_gate_not_fail: bool = True
    allow_quality_gate_warn: bool = True
    rollback_after_run: bool = True
    feature_flag_name: str = "enable_dsl_aware_candidate_extraction_write"

    @classmethod
    def from_env(cls) -> "CandidateExtractionWriteConfig":
        return cls(
            enabled=os.getenv(ENABLE_ENV) == "1",
            run_live_llm=os.getenv(LIVE_LLM_ENV) == "1",
            run_gleaning=os.getenv(GLEANING_ENV) == "1",
            max_samples=_env_int(MAX_SAMPLES_ENV, DEFAULT_MAX_SAMPLES),
        )


@dataclass
class CandidateExtractionReport:
    enabled: bool
    skipped: bool
    skip_reason: str | None
    extraction_run_id: str
    document_id: str | None
    sample_count: int
    native_extract_called: bool
    live_llm_used: bool
    candidate_entity_count: int
    candidate_relation_count: int
    valid_entity_count: int
    valid_relation_count: int
    invalid_entity_count: int
    invalid_relation_count: int
    review_required_count: int
    missing_evidence_count: int
    duplicate_candidate_count: int
    candidate_store_written_count: int
    candidate_store_deleted_count: int
    candidate_store_reset_supported: bool
    rollback_passed: bool
    graph_written: bool
    merge_called: bool
    entities_vdb_written: bool
    relationships_vdb_written: bool
    full_docs_written: bool
    doc_status_written: bool
    quality_summary: dict[str, Any]
    recommended_next_step: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    candidate_entities: list[CandidateEntity] = field(default_factory=list)
    candidate_relations: list[CandidateRelation] = field(default_factory=list)


def run_candidate_extraction_write_dry_run(
    payload: DslAwareIngestionPayload,
    *,
    config: CandidateExtractionWriteConfig | None = None,
    candidate_store: CandidateStore | None = None,
    llm_callable=None,
) -> CandidateExtractionReport:
    config = config or CandidateExtractionWriteConfig()
    extraction_run_id = _extraction_run_id(payload.document_id)
    candidate_store = candidate_store or CandidateStore()

    if not config.enabled:
        return _skipped_report(
            payload,
            extraction_run_id,
            "Feature flag enable_dsl_aware_candidate_extraction_write is disabled.",
            recommended_next_step="ENABLE_FEATURE_FLAG_TO_WRITE_CANDIDATES",
        )
    if config.write_graph or config.call_merge:
        return _blocked_report(
            payload,
            extraction_run_id,
            "FORMAL_STORE_WRITE_ATTEMPTED",
            "Graph write and merge are forbidden for candidate-only dry-run.",
        )
    if _quality_gate_status(payload) == "FAIL" and config.require_quality_gate_not_fail:
        return _blocked_report(
            payload,
            extraction_run_id,
            "QUALITY_GATE_FAIL",
            "Payload qualityGate.status is FAIL.",
            recommended_next_step="DO_NOT_WRITE_CANDIDATES",
        )
    if not config.call_extract_entities:
        return _blocked_report(
            payload,
            extraction_run_id,
            "EXTRACT_ENTITIES_DISABLED",
            "Candidate write requires extract_entities dry-run input.",
        )
    if config.run_live_llm and os.getenv(LIVE_LLM_ENV) != "1":
        return _skipped_report(
            payload,
            extraction_run_id,
            "Set LIGHTRAG_DSL_CANDIDATE_WRITE_LIVE_LLM=1 to run live candidate write.",
            recommended_next_step="ENABLE_LIVE_LLM_ENV_TO_WRITE_CANDIDATES",
        )

    risks: list[str] = []
    extract_config = _extract_config(config, risks)
    extract_report = run_extract_entities_dry_run_from_payload(
        payload,
        llm_callable=llm_callable if config.run_live_llm else None,
        config=extract_config,
    )
    entities, relations, issues = build_candidates_from_extract_result(
        extract_report,
        payload=payload,
        extraction_run_id=extraction_run_id,
    )

    store_written_count = 0
    deleted_count = 0
    before_count = candidate_store.count_all()
    if config.write_candidate_store:
        store_written_count += candidate_store.upsert_entities(entities)
        store_written_count += candidate_store.upsert_relations(relations)
    duplicate_count = candidate_store.duplicate_candidate_count

    rollback_passed = False
    if config.rollback_after_run:
        deleted_count = candidate_store.delete_candidates(
            [candidate.candidate_id for candidate in entities]
            + [candidate.candidate_id for candidate in relations]
        )
        rollback_passed = candidate_store.count_all() == before_count

    return _report_from_candidates(
        payload=payload,
        extraction_run_id=extraction_run_id,
        extract_report=extract_report,
        entities=entities,
        relations=relations,
        issues=issues,
        risks=[*risks, *extract_report.risks],
        candidate_store_written_count=store_written_count,
        candidate_store_deleted_count=deleted_count,
        duplicate_candidate_count=duplicate_count,
        rollback_passed=rollback_passed,
    )


def build_candidates_from_extract_result(
    extract_result: ExtractEntitiesDryRunReport,
    *,
    extraction_items: list[Any] | None = None,
    payload: DslAwareIngestionPayload | None = None,
    extraction_run_id: str,
) -> tuple[list[CandidateEntity], list[CandidateRelation], list[CandidateExtractionIssue]]:
    contexts = _contexts_from_payload(payload) if payload is not None else {}
    contexts.update(_contexts_from_items(extraction_items or []))
    entities: list[CandidateEntity] = []
    relations: list[CandidateRelation] = []
    issues: list[CandidateExtractionIssue] = []

    for sample in extract_result.sample_results:
        context = contexts.get(sample.sample_id, {})
        allowed_entities = _string_list(context.get("allowedEntityTypes"))
        allowed_relations = _string_list(context.get("allowedRelationTypes"))
        for raw_entity in sample.extracted_entities:
            candidate = _candidate_entity_from_raw(
                raw_entity,
                context=context,
                fallback_sample=sample,
                extraction_run_id=extraction_run_id,
            )
            candidate = validate_candidate_entity(candidate, allowed_entities)
            entities.append(candidate)
            issues.extend(_issues_for_candidate(candidate))
        for raw_relation in sample.extracted_relations:
            candidate_relation = _candidate_relation_from_raw(
                raw_relation,
                context=context,
                fallback_sample=sample,
                extraction_run_id=extraction_run_id,
            )
            candidate_relation = validate_candidate_relation(
                candidate_relation,
                allowed_relations,
            )
            relations.append(candidate_relation)
            issues.extend(_issues_for_candidate(candidate_relation))

    issues.extend(_duplicate_issues(entities, relations))
    return entities, relations, issues


def serialize_candidate_extraction_report(
    report: CandidateExtractionReport,
) -> dict[str, Any]:
    return {
        "enabled": report.enabled,
        "skipped": report.skipped,
        "skipReason": report.skip_reason,
        "extractionRunId": report.extraction_run_id,
        "documentId": report.document_id,
        "sampleCount": report.sample_count,
        "nativeExtractCalled": report.native_extract_called,
        "liveLlmUsed": report.live_llm_used,
        "candidateEntityCount": report.candidate_entity_count,
        "candidateRelationCount": report.candidate_relation_count,
        "validEntityCount": report.valid_entity_count,
        "validRelationCount": report.valid_relation_count,
        "invalidEntityCount": report.invalid_entity_count,
        "invalidRelationCount": report.invalid_relation_count,
        "reviewRequiredCount": report.review_required_count,
        "missingEvidenceCount": report.missing_evidence_count,
        "duplicateCandidateCount": report.duplicate_candidate_count,
        "candidateStoreWrittenCount": report.candidate_store_written_count,
        "candidateStoreDeletedCount": report.candidate_store_deleted_count,
        "candidateStoreResetSupported": report.candidate_store_reset_supported,
        "rollbackPassed": report.rollback_passed,
        "graphWritten": report.graph_written,
        "mergeCalled": report.merge_called,
        "entitiesVdbWritten": report.entities_vdb_written,
        "relationshipsVdbWritten": report.relationships_vdb_written,
        "fullDocsWritten": report.full_docs_written,
        "docStatusWritten": report.doc_status_written,
        "qualitySummary": report.quality_summary,
        "recommendedNextStep": report.recommended_next_step,
        "issues": report.issues,
        "risks": report.risks,
        "candidateEntities": [asdict(entity) for entity in report.candidate_entities],
        "candidateRelations": [asdict(relation) for relation in report.candidate_relations],
    }


def _candidate_entity_from_raw(
    raw: dict[str, Any],
    *,
    context: dict[str, Any],
    fallback_sample,
    extraction_run_id: str,
) -> CandidateEntity:
    entity_name = str(raw.get("entity_name") or raw.get("entityName") or "")
    entity_type = str(raw.get("entity_type") or raw.get("entityType") or "")
    description = str(raw.get("description") or "")
    text_hash = _string_or_none(context.get("textHash"))
    source_text_unit_id = _string_or_none(context.get("textUnitId")) or fallback_sample.sample_id
    return CandidateEntity(
        candidate_id=_stable_candidate_id(
            "entity",
            entity_name,
            entity_type,
            _string_or_none(context.get("featureKey")),
            source_text_unit_id,
            text_hash,
        ),
        entity_name=entity_name,
        entity_type=entity_type,
        description=description,
        domain_code=_string_or_none(context.get("domainCode")) or fallback_sample.domain_code,
        feature_key=_string_or_none(context.get("featureKey")) or fallback_sample.feature_key,
        source_us_id=_string_or_none(context.get("sourceUsId")) or fallback_sample.source_us_id,
        source_text_unit_id=source_text_unit_id,
        section_type=_string_or_none(context.get("sectionType")) or fallback_sample.section_type,
        source_span=_dict_or_none(context.get("sourceSpan")),
        text_hash=text_hash,
        evidence_text=_string_or_none(context.get("evidenceText")),
        extraction_run_id=extraction_run_id,
        raw={
            **dict(raw),
            "allowedEntityTypes": _string_list(context.get("allowedEntityTypes")),
            "allowedRelationTypes": _string_list(context.get("allowedRelationTypes")),
            "knownObjects": context.get("knownObjects") if isinstance(context.get("knownObjects"), list) else [],
        },
    )


def _candidate_relation_from_raw(
    raw: dict[str, Any],
    *,
    context: dict[str, Any],
    fallback_sample,
    extraction_run_id: str,
) -> CandidateRelation:
    source_entity = str(raw.get("source_entity") or raw.get("sourceEntity") or "")
    target_entity = str(raw.get("target_entity") or raw.get("targetEntity") or "")
    keywords = str(raw.get("relationship_keywords") or raw.get("relationshipKeywords") or "")
    relation_type = _string_or_none(raw.get("relation_type") or raw.get("relationType"))
    text_hash = _string_or_none(context.get("textHash"))
    source_text_unit_id = _string_or_none(context.get("textUnitId")) or fallback_sample.sample_id
    return CandidateRelation(
        candidate_id=_stable_candidate_id(
            "relation",
            source_entity,
            target_entity,
            relation_type or keywords,
            _string_or_none(context.get("featureKey")),
            source_text_unit_id,
            text_hash,
        ),
        source_entity_name=source_entity,
        target_entity_name=target_entity,
        relation_type=relation_type,
        relationship_keywords=keywords,
        description=str(raw.get("description") or ""),
        domain_code=_string_or_none(context.get("domainCode")) or fallback_sample.domain_code,
        feature_key=_string_or_none(context.get("featureKey")) or fallback_sample.feature_key,
        source_us_id=_string_or_none(context.get("sourceUsId")) or fallback_sample.source_us_id,
        source_text_unit_id=source_text_unit_id,
        section_type=_string_or_none(context.get("sectionType")) or fallback_sample.section_type,
        source_span=_dict_or_none(context.get("sourceSpan")),
        text_hash=text_hash,
        evidence_text=_string_or_none(context.get("evidenceText")),
        extraction_run_id=extraction_run_id,
        raw={
            **dict(raw),
            "allowedEntityTypes": _string_list(context.get("allowedEntityTypes")),
            "allowedRelationTypes": _string_list(context.get("allowedRelationTypes")),
            "knownObjects": context.get("knownObjects") if isinstance(context.get("knownObjects"), list) else [],
        },
    )


def _contexts_from_payload(payload: DslAwareIngestionPayload) -> dict[str, dict[str, Any]]:
    vector_by_chunk = {item.chunk_id: item for item in payload.vector_payload}
    contexts: dict[str, dict[str, Any]] = {}
    for item in payload.extraction_payload:
        metadata = dict(item.metadata)
        source_chunk_id = str(metadata.get("sourceChunkId") or item.chunk_id)
        vector = vector_by_chunk.get(source_chunk_id)
        contexts[source_chunk_id] = {
            **metadata,
            "evidenceText": vector.content if vector is not None else _source_text(item.content),
        }
    return contexts


def _contexts_from_items(extraction_items: list[Any]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for item in extraction_items:
        if isinstance(item, dict):
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            sample_id = str(item.get("sample_id") or item.get("chunk_id") or "")
            if sample_id:
                contexts[sample_id] = dict(metadata)
    return contexts


def _report_from_candidates(
    *,
    payload: DslAwareIngestionPayload,
    extraction_run_id: str,
    extract_report: ExtractEntitiesDryRunReport,
    entities: list[CandidateEntity],
    relations: list[CandidateRelation],
    issues: list[CandidateExtractionIssue],
    risks: list[str],
    candidate_store_written_count: int,
    candidate_store_deleted_count: int,
    duplicate_candidate_count: int,
    rollback_passed: bool,
) -> CandidateExtractionReport:
    valid_entity_count = _count_status(entities, VALIDATION_VALID)
    valid_relation_count = _count_status(relations, VALIDATION_VALID)
    invalid_entity_count = _count_status(entities, VALIDATION_INVALID_TYPE)
    invalid_relation_count = _count_status(relations, VALIDATION_INVALID_TYPE)
    review_required_count = _count_status(entities, VALIDATION_REVIEW_REQUIRED) + _count_status(
        relations,
        VALIDATION_REVIEW_REQUIRED,
    )
    missing_evidence_count = _count_status(entities, VALIDATION_MISSING_EVIDENCE) + _count_status(
        relations,
        VALIDATION_MISSING_EVIDENCE,
    )
    quality_summary = {
        "validEntityCount": valid_entity_count,
        "validRelationCount": valid_relation_count,
        "invalidEntityCount": invalid_entity_count,
        "invalidRelationCount": invalid_relation_count,
        "reviewRequiredCount": review_required_count,
        "missingEvidenceCount": missing_evidence_count,
        "candidateOnly": True,
    }
    return CandidateExtractionReport(
        enabled=True,
        skipped=False,
        skip_reason=None,
        extraction_run_id=extraction_run_id,
        document_id=payload.document_id,
        sample_count=extract_report.sample_count,
        native_extract_called=extract_report.native_extract_called,
        live_llm_used=extract_report.live_llm_used,
        candidate_entity_count=len(entities),
        candidate_relation_count=len(relations),
        valid_entity_count=valid_entity_count,
        valid_relation_count=valid_relation_count,
        invalid_entity_count=invalid_entity_count,
        invalid_relation_count=invalid_relation_count,
        review_required_count=review_required_count,
        missing_evidence_count=missing_evidence_count,
        duplicate_candidate_count=duplicate_candidate_count,
        candidate_store_written_count=candidate_store_written_count,
        candidate_store_deleted_count=candidate_store_deleted_count,
        candidate_store_reset_supported=True,
        rollback_passed=rollback_passed,
        graph_written=False,
        merge_called=False,
        entities_vdb_written=False,
        relationships_vdb_written=False,
        full_docs_written=False,
        doc_status_written=False,
        quality_summary=quality_summary,
        recommended_next_step=_recommended_next_step(
            invalid_entity_count=invalid_entity_count,
            invalid_relation_count=invalid_relation_count,
            review_required_count=review_required_count,
            missing_evidence_count=missing_evidence_count,
        ),
        issues=[asdict(issue) for issue in issues],
        risks=risks,
        candidate_entities=entities,
        candidate_relations=relations,
    )


def _skipped_report(
    payload: DslAwareIngestionPayload,
    extraction_run_id: str,
    reason: str,
    *,
    recommended_next_step: str,
) -> CandidateExtractionReport:
    return CandidateExtractionReport(
        enabled=False,
        skipped=True,
        skip_reason=reason,
        extraction_run_id=extraction_run_id,
        document_id=payload.document_id,
        sample_count=0,
        native_extract_called=False,
        live_llm_used=False,
        candidate_entity_count=0,
        candidate_relation_count=0,
        valid_entity_count=0,
        valid_relation_count=0,
        invalid_entity_count=0,
        invalid_relation_count=0,
        review_required_count=0,
        missing_evidence_count=0,
        duplicate_candidate_count=0,
        candidate_store_written_count=0,
        candidate_store_deleted_count=0,
        candidate_store_reset_supported=True,
        rollback_passed=False,
        graph_written=False,
        merge_called=False,
        entities_vdb_written=False,
        relationships_vdb_written=False,
        full_docs_written=False,
        doc_status_written=False,
        quality_summary={"skipReason": reason},
        recommended_next_step=recommended_next_step,
    )


def _blocked_report(
    payload: DslAwareIngestionPayload,
    extraction_run_id: str,
    code: str,
    message: str,
    *,
    recommended_next_step: str = "DO_NOT_PROCEED",
) -> CandidateExtractionReport:
    report = _skipped_report(
        payload,
        extraction_run_id,
        message,
        recommended_next_step=recommended_next_step,
    )
    report.enabled = True
    report.issues.append(
        asdict(
            CandidateExtractionIssue(
                severity="ERROR",
                code=code,
                message=message,
            )
        )
    )
    return report


def _extract_config(
    config: CandidateExtractionWriteConfig,
    risks: list[str],
) -> ExtractEntitiesDryRunConfig:
    if config.max_samples > config.hard_max_samples:
        risks.append(
            f"max_samples capped from {config.max_samples} to {config.hard_max_samples}."
        )
    return ExtractEntitiesDryRunConfig(
        enabled=True,
        max_samples=config.max_samples,
        hard_max_samples=config.hard_max_samples,
        run_live_llm=config.run_live_llm,
        run_gleaning=config.run_gleaning,
        max_gleaning_samples=config.max_gleaning_samples,
        use_native_extract_entities=config.use_native_extract_entities,
    )


def _issues_for_candidate(
    candidate: CandidateEntity | CandidateRelation,
) -> list[CandidateExtractionIssue]:
    issues: list[CandidateExtractionIssue] = []
    for issue_code in candidate.issues:
        severity = "ERROR" if issue_code in {"INVALID_ENTITY_TYPE", "INVALID_RELATION_TYPE"} else "WARN"
        issues.append(
            CandidateExtractionIssue(
                severity=severity,
                code=issue_code,
                message=f"{issue_code} for candidate {candidate.candidate_id}.",
                candidate_id=candidate.candidate_id,
                source_text_unit_id=candidate.source_text_unit_id,
            )
        )
    return issues


def _duplicate_issues(
    entities: list[CandidateEntity],
    relations: list[CandidateRelation],
) -> list[CandidateExtractionIssue]:
    issues: list[CandidateExtractionIssue] = []
    seen: set[str] = set()
    for candidate in [*entities, *relations]:
        if candidate.candidate_id in seen:
            issues.append(
                CandidateExtractionIssue(
                    severity="WARN",
                    code="DUPLICATE_CANDIDATE",
                    message=f"Duplicate candidate {candidate.candidate_id}.",
                    candidate_id=candidate.candidate_id,
                    source_text_unit_id=candidate.source_text_unit_id,
                )
            )
        seen.add(candidate.candidate_id)
    return issues


def _stable_candidate_id(*parts: str | None) -> str:
    import hashlib

    raw = "|".join(part or "" for part in parts)
    return f"cand-{hashlib.md5(raw.encode('utf-8')).hexdigest()[:16]}"


def _extraction_run_id(document_id: str | None) -> str:
    return f"candidate-run-{document_id or 'doc'}-{uuid.uuid4().hex[:8]}"


def _quality_gate_status(payload: DslAwareIngestionPayload) -> str:
    quality_gate = payload.summary.get("qualityGate")
    if isinstance(quality_gate, dict):
        status = quality_gate.get("status")
        if isinstance(status, str):
            return status
    return ""


def _source_text(content: str) -> str:
    start = content.find("<SOURCE_TEXT>")
    end = content.find("</SOURCE_TEXT>")
    if start == -1 or end == -1 or end < start:
        return content
    return content[start + len("<SOURCE_TEXT>") : end].strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) and value else None


def _count_status(
    candidates: list[CandidateEntity] | list[CandidateRelation],
    status: str,
) -> int:
    return sum(1 for candidate in candidates if candidate.validation_status == status)


def _recommended_next_step(
    *,
    invalid_entity_count: int,
    invalid_relation_count: int,
    review_required_count: int,
    missing_evidence_count: int,
) -> str:
    if missing_evidence_count:
        return "FIX_CANDIDATE_EVIDENCE_BINDING"
    if invalid_entity_count or invalid_relation_count or review_required_count:
        return "REVIEW_CANDIDATES_BEFORE_PROMOTION"
    return "BUILD_CANDIDATE_REVIEW_REPORT"


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


__all__ = [
    "CandidateExtractionReport",
    "CandidateExtractionWriteConfig",
    "build_candidates_from_extract_result",
    "run_candidate_extraction_write_dry_run",
    "serialize_candidate_extraction_report",
]
