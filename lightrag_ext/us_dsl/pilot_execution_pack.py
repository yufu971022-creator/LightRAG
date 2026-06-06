from __future__ import annotations

import json
import shutil
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .candidate_extraction import (
    CandidateExtractionWriteConfig,
    run_candidate_extraction_write_dry_run,
)
from .candidate_review import build_candidate_review_report_from_candidate_extraction_report
from .dsl_aware_chunk_builder import build_dsl_aware_chunks
from .generalization_audit import run_generalization_audit
from .ingestion_adapter import build_dsl_aware_ingestion_payload
from .module_onboarding import render_module_onboarding_checklist
from .ontology_loader import load_ontology
from .pilot_report_pack import (
    build_pilot_report_pack,
    render_pilot_report_markdown,
    serialize_pilot_report_pack,
)
from .pilot_report_types import PilotReportPack
from .source_text_unit_builder import (
    build_source_text_units,
    detect_us_blocks,
    stable_hash,
)


@dataclass
class PilotExecutionPack:
    execution_id: str
    generated_at: str
    source_file: str
    output_dir: str | None
    document_id: str
    module_name: str
    module_code: str
    source_read: bool
    fixture_copied: bool
    input_validation: dict[str, Any]
    pipeline_counts: dict[str, Any]
    guardrails: dict[str, bool]
    pilot_report_summary: dict[str, Any]
    generated_files: list[str] = field(default_factory=list)
    ac_at_fixture_found: bool = False
    coverage_notes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class PilotExecutionBuildResult:
    execution_pack: PilotExecutionPack
    pilot_report_pack: PilotReportPack
    ingestion_payload_summary: dict[str, Any]


def build_pilot_execution_pack_from_source(
    source_path: str | Path,
    *,
    document_id: str,
    module_name: str,
    module_code: str,
    expected_us_count: int | None = None,
    expected_first_us_id: str | None = None,
    expected_last_us_id: str | None = None,
    output_dir: str | Path | None = None,
    max_candidate_samples: int = 6,
    copy_fixture_if_missing: bool = False,
    fixture_path: str | Path | None = None,
    additional_coverage_notes: list[str] | None = None,
) -> PilotExecutionBuildResult:
    source = Path(source_path)
    content = source.read_text(encoding="utf-8")
    fixture_copied = _copy_fixture_if_requested(
        source,
        fixture_path=fixture_path,
        copy_fixture_if_missing=copy_fixture_if_missing,
    )
    blocks = detect_us_blocks(content)
    input_validation = _validate_blocks(
        blocks,
        expected_us_count=expected_us_count,
        expected_first_us_id=expected_first_us_id,
        expected_last_us_id=expected_last_us_id,
    )
    if input_validation["errorCount"]:
        risks = [issue["message"] for issue in input_validation["issues"]]
    else:
        risks = []

    dsl_result = build_minimal_pilot_dsl_result_from_us_blocks(
        blocks,
        module_code=module_code,
    )
    source_units = build_source_text_units(content, document_id, dsl_result=dsl_result)
    chunk_result = build_dsl_aware_chunks(source_units, dsl_result)
    ingestion_payload = build_dsl_aware_ingestion_payload(
        content,
        document_id=document_id,
        dsl_result=dsl_result,
        file_path=str(source),
    )
    candidate_report = run_candidate_extraction_write_dry_run(
        ingestion_payload,
        config=CandidateExtractionWriteConfig(
            enabled=True,
            max_samples=max_candidate_samples,
            rollback_after_run=True,
        ),
    )
    review_report = build_candidate_review_report_from_candidate_extraction_report(
        candidate_report
    )
    audit_report = run_generalization_audit()
    pilot_report = build_pilot_report_pack(
        ingestion_payload=ingestion_payload,
        candidate_extraction_report=candidate_report,
        candidate_review_report=review_report,
        module_name=module_name,
        source_file=str(source),
        generalization_audit_report=audit_report,
    )
    execution_pack = PilotExecutionPack(
        execution_id=stable_hash(f"{document_id}:{source}", prefix="pilot_exec"),
        generated_at=datetime.now(timezone.utc).isoformat(),
        source_file=str(source),
        output_dir=str(output_dir) if output_dir else None,
        document_id=document_id,
        module_name=module_name,
        module_code=module_code,
        source_read=True,
        fixture_copied=fixture_copied,
        input_validation=input_validation,
        pipeline_counts={
            "sourceUsCount": len(blocks),
            "sourceTextUnitCount": len(source_units),
            "dslAwareChunkCount": len(chunk_result.chunks),
            "sectionTypeDistribution": dict(
                Counter(unit.section_type for unit in source_units)
            ),
            "vectorPayloadCount": len(ingestion_payload.vector_payload),
            "extractionPayloadCount": len(ingestion_payload.extraction_payload),
            "candidateEntityCount": candidate_report.candidate_entity_count,
            "candidateRelationCount": candidate_report.candidate_relation_count,
        },
        guardrails={
            "reportOnly": True,
            "graphWrite": False,
            "gesWrite": False,
            "formalStoreWrite": False,
            "mergeNodesAndEdgesCalled": False,
            "autoPromotion": False,
            "confirmedCount": 0,
            "productionPipeline": False,
        },
        pilot_report_summary={
            "readiness": pilot_report.pilot_readiness.status,
            "humanReviewRatio": pilot_report.review_summary["humanReviewRatio"],
            "reviewRequiredCount": pilot_report.review_summary["reviewRequiredCount"],
            "blockedCount": pilot_report.review_summary["blockedCount"],
        },
        ac_at_fixture_found=False,
        coverage_notes=[
            "Current run validates only the provided module source file.",
            *(additional_coverage_notes or []),
        ],
        risks=risks,
        recommendations=[
            "Use this pack for report-only internal pilot review.",
            "Add new module fixture and module registry before claiming coverage for another module.",
        ],
    )
    return PilotExecutionBuildResult(
        execution_pack=execution_pack,
        pilot_report_pack=pilot_report,
        ingestion_payload_summary=ingestion_payload.summary,
    )


def build_minimal_pilot_dsl_result_from_us_blocks(
    blocks,
    *,
    module_code: str,
) -> dict[str, Any]:
    ontology = load_ontology()
    features = []
    plans = []
    gleaning_blocks = []
    active_domains = []

    for block in blocks:
        primary_domain = _normalize_meta_value(
            _extract_meta_value(block.text, "Primary Domain")
        )
        feature_catalog = _normalize_meta_value(
            _extract_meta_value(block.text, "Feature Catalog")
        )
        if not primary_domain:
            primary_domain = "RuleManagement"
        if not feature_catalog:
            feature_catalog = block.title or block.us_id
        feature_key = f"{primary_domain}:{module_code}:{feature_catalog}"
        features.append(
            {
                "featureKey": feature_key,
                "featureName": block.title,
                "primaryDomain": primary_domain,
                "relatedDomains": [],
                "sourceUsIds": [block.us_id],
                "latestFlag": True,
            }
        )
        plans.append(
            {
                "sourceUsId": block.us_id,
                "featureKey": feature_key,
                "domainCode": primary_domain,
                "sectionType": "business_rule",
                "targetCollections": ["source_text_unit_vector", "rule_chunk_vector"],
                "sourceChunkRequired": True,
                "dslContextRequired": True,
            }
        )
        gleaning_blocks.append(
            {
                "sourceType": "DslAwareGleaningInput",
                "featureKey": feature_key,
                "domainCode": primary_domain,
                "sourceUsIds": [block.us_id],
                "allowedEntityTypes": sorted(ontology.allowed_entity_types(primary_domain)),
                "allowedRelationTypes": sorted(ontology.allowed_relation_types(primary_domain)),
                "instruction": (
                    "Extract only from allowedEntityTypes and allowedRelationTypes. "
                    "Do not invent labels. Separate entityType and entityName. "
                    "Preserve evidence."
                ),
            }
        )
        if primary_domain not in active_domains:
            active_domains.append(primary_domain)

    return {
        "dslVersion": "9.4.0",
        "outputFormat": "json-only",
        "fixedDomains": sorted(ontology.domains),
        "runSummary": {"activeDomains": active_domains},
        "activeDomainOverview": [
            {"domainCode": domain_code} for domain_code in active_domains
        ],
        "versionManagement": {},
        "featureCatalogIndex": features,
        "sourceVectorizationPlan": plans,
        "gleaningInputBlocks": gleaning_blocks,
        "confirmedDslObjects": {
            "entities": [],
            "relations": [],
            "fieldSpecs": [],
            "ruleAtoms": [],
            "stateTransitions": [],
            "taskRules": [],
        },
        "termNormalization": {"confirmedSynonymHits": []},
    }


def write_pilot_execution_files(
    build_result: PilotExecutionBuildResult,
    output_dir: str | Path,
    *,
    file_prefix: str = "lc",
) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report_pack = build_result.pilot_report_pack
    execution_pack = build_result.execution_pack
    files = {
        f"{file_prefix}_pilot_report_pack.json": json.dumps(
            serialize_pilot_report_pack(report_pack),
            ensure_ascii=False,
            indent=2,
        ),
        f"{file_prefix}_pilot_report_pack.md": render_pilot_report_markdown(report_pack),
        f"{file_prefix}_pilot_execution_pack.json": json.dumps(
            serialize_pilot_execution_pack(execution_pack),
            ensure_ascii=False,
            indent=2,
        ),
        f"{file_prefix}_pilot_execution_pack.md": render_pilot_execution_pack_markdown(
            execution_pack
        ),
        f"{file_prefix}_ba_se_review_checklist.md": render_ba_se_review_checklist(
            report_pack
        ),
        f"{file_prefix}_pilot_feedback_form.md": render_pilot_feedback_form(),
        f"{file_prefix}_module_onboarding_checklist.md": render_module_onboarding_checklist(
            module_name=execution_pack.module_name,
            module_fixture_found=True,
            additional_module_fixture_note=(
                "Additional module fixture not found in this run; add it before claiming coverage for that module."
            ),
        ),
        f"{file_prefix}_pilot_summary_report.md": render_pilot_summary_report(
            report_pack,
            execution_pack,
        ),
    }
    written: list[Path] = []
    for name, content in files.items():
        path = output / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    execution_pack.generated_files = [str(path) for path in written]
    (output / f"{file_prefix}_pilot_execution_pack.json").write_text(
        json.dumps(serialize_pilot_execution_pack(execution_pack), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return written


def serialize_pilot_execution_pack(report: PilotExecutionPack) -> dict[str, Any]:
    return asdict(report)


def render_pilot_execution_pack_markdown(report: PilotExecutionPack) -> str:
    return "\n".join(
        [
            f"# {report.module_name} Pilot Execution Pack",
            "",
            "## Summary",
            f"- Source file: {report.source_file}",
            f"- Document ID: {report.document_id}",
            f"- Module: {report.module_name}",
            f"- Source read: {str(report.source_read).lower()}",
            f"- Fixture copied: {str(report.fixture_copied).lower()}",
            "",
            "## Validation",
            f"- US count: {report.input_validation['usCount']}",
            f"- First US ID: {report.input_validation['firstUsId']}",
            f"- Last US ID: {report.input_validation['lastUsId']}",
            f"- Error count: {report.input_validation['errorCount']}",
            "",
            "## Guardrails",
            "- report_only: true",
            f"- graph_write: {str(report.guardrails['graphWrite']).lower()}",
            f"- ges_write: {str(report.guardrails['gesWrite']).lower()}",
            f"- auto_promotion: {str(report.guardrails['autoPromotion']).lower()}",
            f"- confirmed_count: {report.guardrails['confirmedCount']}",
            f"- merge_nodes_and_edges_called: {str(report.guardrails['mergeNodesAndEdgesCalled']).lower()}",
            f"- production_pipeline: {str(report.guardrails['productionPipeline']).lower()}",
            "",
            "## Counts",
            *[f"- {key}: {value}" for key, value in report.pipeline_counts.items()],
            "",
            "## Pilot Readiness",
            f"- readiness: {report.pilot_report_summary['readiness']}",
            f"- human_review_ratio: {report.pilot_report_summary['humanReviewRatio']}",
            f"- review_required_count: {report.pilot_report_summary['reviewRequiredCount']}",
            "",
            "## Coverage Note",
            *[f"- {note}" for note in report.coverage_notes],
        ]
    )


def render_ba_se_review_checklist(report: PilotReportPack) -> str:
    review_line = (
        "当前无必须人工确认项"
        if not report.review_required_section
        else "逐条检查 Review-required Items。"
    )
    return "\n".join(
        [
            "# BA/SE Review Checklist",
            "",
            "## Guardrails",
            "- 确认这是 report-only 试点包。",
            "- 确认所有 Candidate 仍为 Candidate，不是 Confirmed。",
            "- 确认没有 auto promotion。",
            "- 确认没有写 graph / GES / formal store。",
            "",
            "## Review Scope",
            f"- Source US count: {report.source_us_count}",
            f"- Source text unit count: {report.source_text_unit_count}",
            f"- Human review ratio: {report.review_summary['humanReviewRatio']}",
            f"- Review-required: {report.review_summary['reviewRequiredCount']}",
            f"- {review_line}",
            "",
            "## Evidence Check",
            "- 抽查 sourceUsId、textUnitId、textHash、evidenceText 是否能回到原文。",
            "- 如果 evidence 不完整，请在反馈表中标记 Missing Evidence。",
            "",
            "## Version / Term Check",
            "- 如果出现版本冲突，请确认当前有效规则是哪一条。",
            "- 如果出现术语歧义，请确认标准术语。",
        ]
    )


def render_pilot_feedback_form() -> str:
    return "\n".join(
        [
            "# Pilot Feedback Form",
            "",
            "- issue_type: [VersionConflict | TermAmbiguity | MissingEvidence | OntologyMapping | ExtractionNoise | Other]",
            "- featureKey:",
            "- sourceUsId:",
            "- candidateId:",
            "- severity: [High | Medium | Low]",
            "- feedback:",
            "- suggested_fix:",
            "- reviewer:",
            "- review_date:",
        ]
    )


def render_pilot_summary_report(
    report: PilotReportPack,
    execution_pack: PilotExecutionPack,
) -> str:
    return "\n".join(
        [
            f"# {execution_pack.module_name} Pilot Summary Report",
            "",
            "## Result",
            f"- Readiness: {report.pilot_readiness.status}",
            f"- Source US count: {report.source_us_count}",
            f"- Source text unit count: {report.source_text_unit_count}",
            f"- DSL-aware chunk count: {report.dsl_aware_chunk_count}",
            f"- Candidate entities: {report.candidate_entity_count}",
            f"- Candidate relations: {report.candidate_relation_count}",
            f"- Auto accept: {report.review_summary['autoAcceptCount']}",
            f"- Auto resolve: {report.review_summary['autoResolveCount']}",
            f"- Info only: {report.review_summary['infoOnlyCount']}",
            f"- Review required: {report.review_summary['reviewRequiredCount']}",
            f"- Blocked: {report.review_summary['blockedCount']}",
            f"- Human review ratio: {report.review_summary['humanReviewRatio']}",
            "",
            "## Safety",
            f"- graph_write: {str(execution_pack.guardrails['graphWrite']).lower()}",
            f"- ges_write: {str(execution_pack.guardrails['gesWrite']).lower()}",
            f"- auto_promotion: {str(execution_pack.guardrails['autoPromotion']).lower()}",
            f"- confirmed_count: {execution_pack.guardrails['confirmedCount']}",
            "",
            "## Review Required",
            "- 当前无必须人工确认项" if not report.review_required_section else "- See Review-required Items in Pilot Report Pack.",
            "",
            "## INFO_ONLY",
            "- INFO_ONLY items are not formal facts, not graph writes, and require no manual review.",
            "",
            "## Module Coverage",
            *[f"- {note}" for note in execution_pack.coverage_notes],
            "- New modules must add their own fixture and optional module registry, then rerun this flow.",
        ]
    )


def _validate_blocks(
    blocks,
    *,
    expected_us_count: int | None,
    expected_first_us_id: str | None,
    expected_last_us_id: str | None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if expected_us_count is not None and len(blocks) != expected_us_count:
        issues.append({"code": "US_COUNT_MISMATCH", "message": f"Expected {expected_us_count}, got {len(blocks)}."})
    first = blocks[0].us_id if blocks else None
    last = blocks[-1].us_id if blocks else None
    if expected_first_us_id is not None and first != expected_first_us_id:
        issues.append({"code": "FIRST_US_ID_MISMATCH", "message": f"Expected {expected_first_us_id}, got {first}."})
    if expected_last_us_id is not None and last != expected_last_us_id:
        issues.append({"code": "LAST_US_ID_MISMATCH", "message": f"Expected {expected_last_us_id}, got {last}."})
    return {
        "usCount": len(blocks),
        "firstUsId": first,
        "lastUsId": last,
        "errorCount": len(issues),
        "issues": issues,
    }


def _copy_fixture_if_requested(
    source: Path,
    *,
    fixture_path: str | Path | None,
    copy_fixture_if_missing: bool,
) -> bool:
    if not copy_fixture_if_missing or fixture_path is None:
        return False
    target = Path(fixture_path)
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return True


def _extract_meta_value(text: str, label: str) -> str:
    prefix = f"- **{label}**："
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _normalize_meta_value(value: str) -> str:
    return value.strip().strip("`").strip()


__all__ = [
    "PilotExecutionBuildResult",
    "PilotExecutionPack",
    "build_minimal_pilot_dsl_result_from_us_blocks",
    "build_pilot_execution_pack_from_source",
    "render_ba_se_review_checklist",
    "render_pilot_execution_pack_markdown",
    "render_pilot_feedback_form",
    "render_pilot_summary_report",
    "serialize_pilot_execution_pack",
    "write_pilot_execution_files",
]
