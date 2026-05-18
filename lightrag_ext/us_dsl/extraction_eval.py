from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from .extraction_metrics import (
    DEFAULT_COMPLETION_DELIMITER,
    DEFAULT_TUPLE_DELIMITER,
    ExtractionComparisonMetrics,
    ExtractionRunResult,
    compare_extraction_results,
    parse_tuple_extraction_output,
)
from .payload_types import DslAwareIngestionPayload
from .pipeline_mapping import PipelineMappingPlan


DEFAULT_PREFERRED_SECTIONS = [
    "field_table",
    "state_rule",
    "task_rule",
    "api_desc",
    "report_rule",
    "migration_rule",
    "business_rule",
    "message_rule",
    "dfx_rule",
    "gwt",
]
DEFAULT_PREFERRED_DOMAINS = [
    "Ledger",
    "Workflow",
    "MonitoringReport",
    "Integration",
    "AccessAudit",
    "RuleManagement",
    "DataMigrationInitialization",
]
EVIDENCE_KEYWORDS = [
    "Deal Number",
    "Agent Bank",
    "Pricing Type",
    "Buy Currency",
    "Sell Currency",
    "Approve",
    "No permission",
    "Audit History",
    "Status",
    "Not Found",
    "pagesize",
    "Create Time",
    "Final Approval",
    "Bank Rating",
    "Acceptable Tenor",
    "Swift Code",
    "Bank Internal Code",
    "不允许修改",
    "Bank Status",
    "Normal(New)",
    "Removed",
    "Not Involved",
    "Bank Default Confirmation",
    "To be confirmed",
    "Current Handler",
    "Transfer To",
    "防重",
    "API",
    "MQ",
    "eflowNum",
    "Suggested Rating",
    "No permission",
    "AuditLog",
    "OperationLog",
    "Data Scope",
    "历史数据迁移",
    "dry-run",
    "SourceVectorizationPlan",
    "GleaningInputBlocks",
    "CandidateEntity",
    "CandidateRelation",
]


@dataclass(frozen=True)
class ExtractionInputPair:
    sample_id: str
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str
    baseline_input: str
    dsl_aware_input: str
    allowed_entity_types: list[str]
    allowed_relation_types: list[str]
    expected_entities: list[dict[str, Any]]
    expected_relations: list[dict[str, Any]]
    evidence_keywords: list[str]


@dataclass
class ExtractionEvaluationReport:
    mode: str
    live_llm_used: bool
    sample_count: int
    metrics: list[ExtractionComparisonMetrics]
    aggregate_summary: dict[str, Any]
    issues: list[dict[str, Any]] = field(default_factory=list)


def select_extraction_eval_samples(
    payload_or_mapping: DslAwareIngestionPayload | PipelineMappingPlan,
    *,
    max_samples: int = 8,
    preferred_sections: list[str] | None = None,
    preferred_domains: list[str] | None = None,
) -> list[ExtractionInputPair]:
    preferred_sections = preferred_sections or DEFAULT_PREFERRED_SECTIONS
    preferred_domains = preferred_domains or DEFAULT_PREFERRED_DOMAINS
    candidates = _input_pairs(payload_or_mapping)
    candidates = [
        candidate
        for candidate in candidates
        if candidate.section_type in preferred_sections
        or candidate.domain_code in preferred_domains
    ]
    selected: list[ExtractionInputPair] = []
    used_ids: set[str] = set()
    used_sections: set[str] = set()
    used_domains: set[str] = set()

    while candidates and len(selected) < max_samples:
        best = min(
            candidates,
            key=lambda candidate: _candidate_score(
                candidate,
                preferred_sections=preferred_sections,
                preferred_domains=preferred_domains,
                used_sections=used_sections,
                used_domains=used_domains,
            ),
        )
        selected.append(best)
        used_ids.add(best.sample_id)
        used_sections.add(best.section_type)
        if best.domain_code:
            used_domains.add(best.domain_code)
        candidates = [
            candidate for candidate in candidates if candidate.sample_id not in used_ids
        ]

    return selected


def run_offline_extraction_evaluation(
    pairs: list[ExtractionInputPair],
) -> ExtractionEvaluationReport:
    metrics: list[ExtractionComparisonMetrics] = []
    issues: list[dict[str, Any]] = []

    for pair in pairs:
        baseline = run_deterministic_extraction_pair(pair, mode="baseline")
        dsl_aware = run_deterministic_extraction_pair(pair, mode="dsl_aware")
        metrics.append(
            compare_extraction_results(
                sample_id=pair.sample_id,
                domain_code=pair.domain_code or "",
                section_type=pair.section_type,
                allowed_entity_types=pair.allowed_entity_types,
                allowed_relation_types=pair.allowed_relation_types,
                expected_entities=pair.expected_entities,
                expected_relations=pair.expected_relations,
                evidence_keywords=pair.evidence_keywords,
                baseline_result=baseline,
                dsl_result=dsl_aware,
            )
        )
        for parse_error in [*baseline.parse_errors, *dsl_aware.parse_errors]:
            issues.append(
                {
                    "severity": "WARN",
                    "code": "TUPLE_PARSE_ERROR",
                    "sampleId": pair.sample_id,
                    "message": parse_error,
                }
            )

    return ExtractionEvaluationReport(
        mode="offline_deterministic",
        live_llm_used=False,
        sample_count=len(pairs),
        metrics=metrics,
        aggregate_summary=_aggregate_summary(metrics, live_llm_used=False),
        issues=issues,
    )


def run_deterministic_extraction_pair(
    pair: ExtractionInputPair,
    *,
    mode: str,
) -> ExtractionRunResult:
    raw_output = deterministic_fake_extraction_output(pair, mode=mode)
    return parse_tuple_extraction_output(
        raw_output,
        sample_id=pair.sample_id,
        mode=mode,
        allowed_relation_types=pair.allowed_relation_types,
    )


def deterministic_fake_extraction_output(
    pair: ExtractionInputPair,
    *,
    mode: str,
) -> str:
    first_entity = _primary_entity_name(pair)
    second_entity = _secondary_entity_name(pair)
    evidence_text = ", ".join(pair.evidence_keywords[:3]) or pair.section_type

    if mode == "dsl_aware":
        first_type = _preferred_entity_type(pair.allowed_entity_types, pair)
        second_type = _secondary_entity_type(pair.allowed_entity_types, pair)
        relation_type = _preferred_relation_type(pair.allowed_relation_types, pair)
    else:
        first_type = _baseline_entity_type(pair)
        second_type = "Field" if pair.section_type == "field_table" else "Object"
        relation_type = _baseline_relation_keyword(pair)

    delimiter = DEFAULT_TUPLE_DELIMITER
    return "\n".join(
        [
            delimiter.join(
                [
                    "entity",
                    first_entity,
                    first_type,
                    f"{first_entity} evidence: {evidence_text}",
                ]
            ),
            delimiter.join(
                [
                    "entity",
                    second_entity,
                    second_type,
                    f"{second_entity} evidence: {evidence_text}",
                ]
            ),
            delimiter.join(
                [
                    "relation",
                    first_entity,
                    second_entity,
                    relation_type,
                    f"{relation_type} evidence: {evidence_text}",
                ]
            ),
            DEFAULT_COMPLETION_DELIMITER,
        ]
    )


def run_lightrag_extract_entities_if_available(*_args, **_kwargs):
    return NotImplemented


def live_smoke_enabled() -> bool:
    return os.getenv("LIGHTRAG_DSL_RUN_LIVE_EXTRACTION") == "1"


def _input_pairs(
    payload_or_mapping: DslAwareIngestionPayload | PipelineMappingPlan,
) -> list[ExtractionInputPair]:
    if isinstance(payload_or_mapping, DslAwareIngestionPayload):
        return _input_pairs_from_payload(payload_or_mapping)
    return _input_pairs_from_mapping(payload_or_mapping)


def _input_pairs_from_payload(
    payload: DslAwareIngestionPayload,
) -> list[ExtractionInputPair]:
    vector_by_chunk = {item.chunk_id: item for item in payload.vector_payload}
    result: list[ExtractionInputPair] = []
    for index, extraction_item in enumerate(payload.extraction_payload):
        source_chunk_id = extraction_item.metadata.get("sourceChunkId")
        vector_item = vector_by_chunk.get(source_chunk_id)
        if vector_item is None:
            continue
        result.append(
            _build_pair(
                sample_id=str(source_chunk_id or extraction_item.chunk_id),
                baseline_input=vector_item.content,
                dsl_aware_input=extraction_item.content,
                metadata=extraction_item.metadata,
                original_index=index,
            )
        )
    return result


def _input_pairs_from_mapping(plan: PipelineMappingPlan) -> list[ExtractionInputPair]:
    vector_by_chunk = {item.chunk_id: item for item in plan.vector_store_mappings}
    result: list[ExtractionInputPair] = []
    for index, extraction_item in enumerate(plan.extraction_mappings):
        source_chunk_id = extraction_item.metadata.get("sourceChunkId")
        vector_item = vector_by_chunk.get(source_chunk_id)
        if vector_item is None:
            continue
        result.append(
            _build_pair(
                sample_id=str(source_chunk_id or extraction_item.chunk_id),
                baseline_input=vector_item.content_preview,
                dsl_aware_input=extraction_item.content_preview,
                metadata=extraction_item.metadata,
                original_index=index,
            )
        )
    return result


def _build_pair(
    *,
    sample_id: str,
    baseline_input: str,
    dsl_aware_input: str,
    metadata: dict[str, Any],
    original_index: int,
) -> ExtractionInputPair:
    allowed_entities = _string_list(metadata.get("allowedEntityTypes"))
    allowed_relations = _string_list(metadata.get("allowedRelationTypes"))
    section_type = str(metadata.get("sectionType") or "unknown")
    domain_code = _string_or_none(metadata.get("domainCode"))
    keywords = _evidence_keywords(baseline_input)
    expected_entity_type = _preferred_entity_type_from_values(
        allowed_entities,
        section_type=section_type,
        domain_code=domain_code,
    )
    expected_relation_type = _preferred_relation_type_from_values(
        allowed_relations,
        section_type=section_type,
        domain_code=domain_code,
    )
    entity_name = keywords[0] if keywords else _fallback_entity_name(metadata)
    secondary_entity_name = keywords[1] if len(keywords) > 1 else section_type
    return ExtractionInputPair(
        sample_id=sample_id,
        source_us_id=_string_or_none(metadata.get("sourceUsId")),
        feature_key=_string_or_none(metadata.get("featureKey")),
        domain_code=domain_code,
        section_type=section_type,
        baseline_input=baseline_input,
        dsl_aware_input=dsl_aware_input,
        allowed_entity_types=allowed_entities,
        allowed_relation_types=allowed_relations,
        expected_entities=[
            {"entityName": entity_name, "entityType": expected_entity_type},
            {"entityName": secondary_entity_name, "entityType": expected_entity_type},
        ],
        expected_relations=[{"relationType": expected_relation_type}],
        evidence_keywords=keywords,
    )


def _candidate_score(
    candidate: ExtractionInputPair,
    *,
    preferred_sections: list[str],
    preferred_domains: list[str],
    used_sections: set[str],
    used_domains: set[str],
) -> tuple[int, int, int, int, str]:
    section_rank = _rank(preferred_sections, candidate.section_type)
    domain_rank = _rank(preferred_domains, candidate.domain_code or "")
    return (
        int(candidate.domain_code in used_domains),
        int(candidate.section_type in used_sections),
        section_rank,
        domain_rank,
        candidate.sample_id,
    )


def _aggregate_summary(
    metrics: list[ExtractionComparisonMetrics],
    *,
    live_llm_used: bool,
) -> dict[str, Any]:
    sample_count = len(metrics)
    improved = sum(1 for item in metrics if item.improvement_label == "IMPROVED")
    degraded = sum(1 for item in metrics if item.improvement_label == "DEGRADED")
    inconclusive = sum(
        1 for item in metrics if item.improvement_label == "INCONCLUSIVE"
    )
    recommended_next_step = _recommended_next_step(
        sample_count=sample_count,
        improved=improved,
        degraded=degraded,
        inconclusive=inconclusive,
        live_llm_used=live_llm_used,
    )
    return {
        "avg_entity_type_hit_rate_delta": _average(
            [item.entity_type_hit_rate_delta for item in metrics]
        ),
        "avg_relation_type_hit_rate_delta": _average(
            [item.relation_type_hit_rate_delta for item in metrics]
        ),
        "total_invalid_entity_type_delta": sum(
            item.invalid_entity_type_delta for item in metrics
        ),
        "total_invalid_relation_type_delta": sum(
            item.invalid_relation_type_delta for item in metrics
        ),
        "total_snake_case_relation_delta": sum(
            item.snake_case_relation_delta for item in metrics
        ),
        "total_candidate_relation_delta": sum(
            item.candidate_relation_delta for item in metrics
        ),
        "improved_sample_count": improved,
        "degraded_sample_count": degraded,
        "inconclusive_sample_count": inconclusive,
        "recommended_next_step": recommended_next_step,
        "covered_domains": sorted({item.domain_code for item in metrics if item.domain_code}),
        "covered_sections": sorted({item.section_type for item in metrics}),
    }


def _recommended_next_step(
    *,
    sample_count: int,
    improved: int,
    degraded: int,
    inconclusive: int,
    live_llm_used: bool,
) -> str:
    if sample_count == 0 or inconclusive > sample_count / 2:
        return "FIX_TUPLE_PARSER_COMPATIBILITY"
    if degraded > improved:
        return "DO_NOT_CONNECT_EXTRACTION"
    if improved > degraded and not live_llm_used:
        return "RUN_OPTIONAL_LIVE_SMOKE"
    if improved > degraded:
        return "PROMPT_CONTEXT_LIVE_SMOKE"
    return "PROMPT_CONTEXT_REVIEW"


def _primary_entity_name(pair: ExtractionInputPair) -> str:
    if pair.expected_entities:
        return str(pair.expected_entities[0].get("entityName") or pair.feature_key)
    return pair.feature_key or pair.sample_id


def _secondary_entity_name(pair: ExtractionInputPair) -> str:
    if len(pair.expected_entities) > 1:
        return str(pair.expected_entities[1].get("entityName") or pair.section_type)
    return pair.section_type


def _preferred_entity_type(
    allowed_entity_types: list[str],
    pair: ExtractionInputPair,
) -> str:
    return _preferred_entity_type_from_values(
        allowed_entity_types,
        section_type=pair.section_type,
        domain_code=pair.domain_code,
    )


def _secondary_entity_type(
    allowed_entity_types: list[str],
    pair: ExtractionInputPair,
) -> str:
    preferred = [
        "RuleAtom",
        "FieldSpec",
        "AuditLog",
        "Workflow",
        "Report",
        "BackendApi",
        "MigrationTask",
        "BusinessRule",
    ]
    for entity_type in preferred:
        if entity_type in allowed_entity_types and entity_type != _preferred_entity_type(
            allowed_entity_types,
            pair,
        ):
            return entity_type
    return _preferred_entity_type(allowed_entity_types, pair)


def _preferred_entity_type_from_values(
    allowed_entity_types: list[str],
    *,
    section_type: str,
    domain_code: str | None,
) -> str:
    preferred_by_section = {
        "field_table": ["FieldSpec", "Deal", "FeatureCatalog"],
        "state_rule": ["ApprovalAction", "Workflow", "WorkflowState"],
        "task_rule": ["TodoTask", "TaskRule", "CurrentHandler"],
        "api_desc": ["BackendApi", "FrontendApi", "Endpoint"],
        "report_rule": ["Report", "SearchCondition", "ReportColumn"],
        "migration_rule": ["MigrationRule", "MigrationTask", "DataMapping"],
        "message_rule": ["MessageAtom", "WarningMessage", "RuleAtom"],
        "dfx_rule": ["DfxControl", "BusinessRule", "RuleAtom"],
    }
    preferred_by_domain = {
        "Ledger": ["Deal", "Transaction", "FieldSpec"],
        "Workflow": ["Workflow", "ApprovalAction", "TaskRule"],
        "MonitoringReport": ["Report", "MonitoringRule", "SearchCondition"],
        "Integration": ["BackendApi", "Endpoint", "ExternalSystem"],
        "AccessAudit": ["AuditLog", "Permission", "OperationLog"],
        "RuleManagement": ["BusinessRule", "ValidationRule", "RuleAtom"],
        "DataMigrationInitialization": ["MigrationRule", "MigrationTask"],
    }
    for entity_type in [
        *preferred_by_section.get(section_type, []),
        *preferred_by_domain.get(domain_code or "", []),
        "FeatureCatalog",
    ]:
        if entity_type in allowed_entity_types:
            return entity_type
    return next(
        (
            entity_type
            for entity_type in allowed_entity_types
            if entity_type != "CandidateEntity"
        ),
        "CandidateEntity",
    )


def _preferred_relation_type(
    allowed_relation_types: list[str],
    pair: ExtractionInputPair,
) -> str:
    return _preferred_relation_type_from_values(
        allowed_relation_types,
        section_type=pair.section_type,
        domain_code=pair.domain_code,
    )


def _preferred_relation_type_from_values(
    allowed_relation_types: list[str],
    *,
    section_type: str,
    domain_code: str | None,
) -> str:
    preferred_by_section = {
        "field_table": ["HasFieldSpec", "HasRequestField", "HasReportColumn"],
        "state_rule": ["Approves", "TransitionsTo", "WritesWorkflowLog"],
        "task_rule": ["GeneratesTask", "TransfersTask", "AssignsHandler"],
        "api_desc": ["CallsBackendApi", "CallsFrontendApi", "IntegratesWith"],
        "report_rule": ["HasReport", "FiltersBy", "ExportsReport"],
        "migration_rule": ["HasMigrationRule", "HasMigrationTask", "MigratesFrom"],
        "message_rule": ["TriggersWarning", "HasMessageAtom", "RelatedTo"],
        "dfx_rule": ["HasBusinessRule", "RequiresDataConsistency", "RelatedTo"],
    }
    preferred_by_domain = {
        "Ledger": ["HasLedgerDetail", "GeneratesLedger", "HasFieldSpec"],
        "Workflow": ["HasWorkflow", "Approves", "GeneratesTask"],
        "MonitoringReport": ["HasReport", "HasMonitoringRule", "FiltersBy"],
        "Integration": ["CallsBackendApi", "ExposesEndpoint", "IntegratesWith"],
        "AccessAudit": ["WritesAuditLog", "RequiresPermission"],
        "RuleManagement": ["HasBusinessRule", "HasValidationRule"],
        "DataMigrationInitialization": ["HasMigrationRule", "MigratesFrom"],
    }
    for relation_type in [
        *preferred_by_section.get(section_type, []),
        *preferred_by_domain.get(domain_code or "", []),
        "DependsOn",
        "RelatedTo",
    ]:
        if relation_type in allowed_relation_types:
            return relation_type
    return next(
        (
            relation_type
            for relation_type in allowed_relation_types
            if relation_type != "CandidateRelation"
        ),
        "CandidateRelation",
    )


def _baseline_entity_type(pair: ExtractionInputPair) -> str:
    if pair.section_type == "field_table":
        return "Field"
    if pair.section_type in {"state_rule", "task_rule"}:
        return "Action"
    if pair.section_type == "api_desc":
        return "API"
    if pair.section_type == "report_rule":
        return "ReportField"
    if pair.section_type == "migration_rule":
        return "DataObject"
    return "Object"


def _baseline_relation_keyword(pair: ExtractionInputPair) -> str:
    if pair.section_type == "report_rule":
        return "queries_from"
    if pair.section_type in {"state_rule", "task_rule", "message_rule"}:
        return "references_to"
    return "has_child"


def _evidence_keywords(text: str) -> list[str]:
    found = [keyword for keyword in EVIDENCE_KEYWORDS if keyword in text]
    if found:
        return _stable_unique(found[:5])
    english_tokens = re.findall(r"[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*", text)
    chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    return _stable_unique([*english_tokens[:3], *chinese_tokens[:2]])[:5]


def _fallback_entity_name(metadata: dict[str, Any]) -> str:
    return (
        _string_or_none(metadata.get("featureKey"))
        or _string_or_none(metadata.get("sourceUsId"))
        or "SourceTextUnit"
    )


def _rank(values: list[str], value: str) -> int:
    try:
        return values.index(value)
    except ValueError:
        return len(values)


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stable_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
