from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ingestion_adapter import build_dsl_aware_ingestion_payload
from .payload_types import DslAwareIngestionPayload
from .pipeline_mapping import (
    build_pipeline_mapping_plan,
    serialize_pipeline_mapping_plan,
)


FEATURE_FLAG_NAME = "enable_dsl_aware_ingestion"
QUALITY_PASS_STATUSES = ("PASS", "WARN")


@dataclass(frozen=True)
class DslAwarePipelineHookConfig:
    enabled: bool = False
    dry_run: bool = True
    dry_run_only: bool = False
    fallback_to_original: bool = True
    strict_quality_gate: bool = False
    block_original_on_dsl_error: bool = False
    report_dir: str | None = None
    report_to_memory: bool = True
    dsl_path_resolve_enabled: bool = True
    feature_flag_name: str = FEATURE_FLAG_NAME
    allowed_quality_gate_status: tuple[str, ...] = QUALITY_PASS_STATUSES
    generate_mapping_plan: bool = False

    @classmethod
    def from_env(cls) -> "DslAwarePipelineHookConfig":
        return cls(
            enabled=_env_bool("LIGHTRAG_ENABLE_DSL_AWARE_INGESTION", False),
            dry_run=_env_bool("LIGHTRAG_DSL_AWARE_DRY_RUN", True),
            dry_run_only=_env_bool("LIGHTRAG_DSL_AWARE_DRY_RUN_ONLY", False),
            strict_quality_gate=_env_bool(
                "LIGHTRAG_DSL_AWARE_STRICT_QUALITY_GATE", False
            ),
            block_original_on_dsl_error=_env_bool(
                "LIGHTRAG_DSL_AWARE_BLOCK_ORIGINAL_ON_ERROR", False
            ),
            report_dir=os.getenv("LIGHTRAG_DSL_AWARE_REPORT_DIR") or None,
            generate_mapping_plan=_env_bool(
                "LIGHTRAG_DSL_AWARE_GENERATE_MAPPING_PLAN", False
            ),
        )


@dataclass(frozen=True)
class DslAwarePipelineDocumentReport:
    document_id: str
    file_path: str | None
    dsl_path: str | None
    dsl_found: bool
    payload_built: bool
    quality_gate_status: str | None = None
    recommended_next_step: str | None = None
    vector_payload_count: int = 0
    extraction_payload_count: int = 0
    metadata_payload_count: int = 0
    source_text_unit_count: int = 0
    dsl_aware_chunk_count: int = 0
    candidate_warn_count: int = 0
    candidate_warn_ratio: float = 0.0
    unmapped_ratio: float = 0.0
    unknown_ratio: float = 0.0
    write_stores: bool = False
    quality_metrics: dict[str, Any] = field(default_factory=dict)
    quality_gate: dict[str, Any] = field(default_factory=dict)
    integration_readiness: dict[str, Any] = field(default_factory=dict)
    pipeline_mapping_plan: dict[str, Any] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "documentId": self.document_id,
            "filePath": self.file_path,
            "dslPath": self.dsl_path,
            "dslFound": self.dsl_found,
            "payloadBuilt": self.payload_built,
            "qualityGateStatus": self.quality_gate_status,
            "recommendedNextStep": self.recommended_next_step,
            "vectorPayloadCount": self.vector_payload_count,
            "extractionPayloadCount": self.extraction_payload_count,
            "metadataPayloadCount": self.metadata_payload_count,
            "sourceTextUnitCount": self.source_text_unit_count,
            "dslAwareChunkCount": self.dsl_aware_chunk_count,
            "candidateWarnCount": self.candidate_warn_count,
            "candidateWarnRatio": self.candidate_warn_ratio,
            "unmappedRatio": self.unmapped_ratio,
            "unknownRatio": self.unknown_ratio,
            "writeStores": self.write_stores,
            "qualityMetrics": self.quality_metrics,
            "qualityGate": self.quality_gate,
            "integrationReadiness": self.integration_readiness,
            "error": self.error,
        }
        if self.pipeline_mapping_plan is not None:
            result["pipelineMappingPlan"] = self.pipeline_mapping_plan
        return result


@dataclass
class DslAwarePipelineHookReport:
    enabled: bool
    dry_run: bool
    dry_run_only: bool
    original_pipeline_called: bool
    fallback_used: bool
    document_reports: list[DslAwarePipelineDocumentReport] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "dryRun": self.dry_run,
            "dryRunOnly": self.dry_run_only,
            "originalPipelineCalled": self.original_pipeline_called,
            "fallbackUsed": self.fallback_used,
            "documentReports": [report.to_dict() for report in self.document_reports],
            "summary": self.summary,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def resolve_dsl_path(
    file_path: str | None,
    explicit_dsl_path: str | None = None,
    dsl_paths_map: dict | None = None,
) -> Path | None:
    explicit = _existing_path(explicit_dsl_path)
    if explicit is not None:
        return explicit

    if dsl_paths_map and file_path is not None:
        mapped = dsl_paths_map.get(file_path) or dsl_paths_map.get(str(file_path))
        mapped_path = _existing_path(mapped)
        if mapped_path is not None:
            return mapped_path

    if file_path is None:
        return None

    path = Path(file_path)
    candidates = [
        path.with_name("dsl-compiled.json"),
        path.with_name(f"{path.stem}.dsl-compiled.json"),
        path.with_name(f"{path.stem}.dsl.json"),
        Path(f"{file_path}.dsl-compiled.json"),
        Path(f"{file_path}.dsl.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


async def ainsert_with_dsl_dry_run(
    rag,
    input,
    *,
    ids=None,
    file_paths=None,
    track_id=None,
    dsl_paths=None,
    split_by_character=None,
    split_by_character_only=False,
    hook_config: DslAwarePipelineHookConfig | None = None,
    **kwargs,
):
    config = hook_config or DslAwarePipelineHookConfig.from_env()
    if not config.enabled:
        original_result = await rag.ainsert(
            input,
            split_by_character=split_by_character,
            split_by_character_only=split_by_character_only,
            ids=ids,
            file_paths=file_paths,
            track_id=track_id,
            **kwargs,
        )
        report = _empty_report(config, original_pipeline_called=True)
        return _wrapper_result(report, original_result)

    report = _build_hook_report(
        input=input,
        ids=ids,
        file_paths=file_paths,
        track_id=track_id,
        dsl_paths=dsl_paths,
        config=config,
    )

    should_call_original = _should_call_original(report, config)
    original_result = None
    if should_call_original:
        original_result = await rag.ainsert(
            input,
            split_by_character=split_by_character,
            split_by_character_only=split_by_character_only,
            ids=ids,
            file_paths=file_paths,
            track_id=track_id,
            **kwargs,
        )
        report.original_pipeline_called = True

    _finalize_report(report)
    _write_report_if_needed(report, config, track_id=track_id)
    return _wrapper_result(report, original_result)


def insert_with_dsl_dry_run(
    rag,
    input,
    *,
    ids=None,
    file_paths=None,
    track_id=None,
    dsl_paths=None,
    split_by_character=None,
    split_by_character_only=False,
    hook_config: DslAwarePipelineHookConfig | None = None,
    **kwargs,
):
    config = hook_config or DslAwarePipelineHookConfig.from_env()
    if not config.enabled:
        original_result = rag.insert(
            input,
            split_by_character=split_by_character,
            split_by_character_only=split_by_character_only,
            ids=ids,
            file_paths=file_paths,
            track_id=track_id,
            **kwargs,
        )
        report = _empty_report(config, original_pipeline_called=True)
        return _wrapper_result(report, original_result)

    report = _build_hook_report(
        input=input,
        ids=ids,
        file_paths=file_paths,
        track_id=track_id,
        dsl_paths=dsl_paths,
        config=config,
    )

    should_call_original = _should_call_original(report, config)
    original_result = None
    if should_call_original:
        original_result = rag.insert(
            input,
            split_by_character=split_by_character,
            split_by_character_only=split_by_character_only,
            ids=ids,
            file_paths=file_paths,
            track_id=track_id,
            **kwargs,
        )
        report.original_pipeline_called = True

    _finalize_report(report)
    _write_report_if_needed(report, config, track_id=track_id)
    return _wrapper_result(report, original_result)


def _build_hook_report(
    input,
    ids,
    file_paths,
    track_id,
    dsl_paths,
    config: DslAwarePipelineHookConfig,
) -> DslAwarePipelineHookReport:
    inputs = _as_list(input)
    id_list = _normalize_optional_list(ids, len(inputs))
    file_path_list = _normalize_optional_list(file_paths, len(inputs))
    explicit_dsl_paths, dsl_paths_map = _normalize_dsl_paths(dsl_paths, len(inputs))
    report = DslAwarePipelineHookReport(
        enabled=True,
        dry_run=config.dry_run,
        dry_run_only=config.dry_run_only,
        original_pipeline_called=False,
        fallback_used=False,
    )

    if not config.dry_run:
        report.warnings.append("DSL-aware hook enabled with dry_run=False; no payload built.")
        _finalize_report(report)
        return report

    for index, content in enumerate(inputs):
        document_id = _document_id(id_list[index], file_path_list[index], index)
        explicit_dsl_path = explicit_dsl_paths[index] if explicit_dsl_paths else None
        dsl_path = (
            resolve_dsl_path(
                file_path_list[index],
                explicit_dsl_path=explicit_dsl_path,
                dsl_paths_map=dsl_paths_map,
            )
            if config.dsl_path_resolve_enabled
            else _existing_path(explicit_dsl_path)
        )

        if dsl_path is None:
            message = f"DSL file not found for document {document_id}."
            report.warnings.append(message)
            report.fallback_used = True
            report.document_reports.append(
                DslAwarePipelineDocumentReport(
                    document_id=document_id,
                    file_path=file_path_list[index],
                    dsl_path=None,
                    dsl_found=False,
                    payload_built=False,
                    error=message,
                )
            )
            continue

        try:
            payload = build_dsl_aware_ingestion_payload(
                content,
                document_id=document_id,
                dsl_path=dsl_path,
                file_path=file_path_list[index],
                validate_dsl=True,
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            report.errors.append(message)
            report.fallback_used = True
            report.document_reports.append(
                DslAwarePipelineDocumentReport(
                    document_id=document_id,
                    file_path=file_path_list[index],
                    dsl_path=str(dsl_path),
                    dsl_found=True,
                    payload_built=False,
                    error=message,
                )
            )
            if config.block_original_on_dsl_error:
                raise
            continue

        doc_report = _document_report_from_payload(
            payload=payload,
            document_id=document_id,
            file_path=file_path_list[index],
            dsl_path=dsl_path,
            generate_mapping_plan=config.generate_mapping_plan,
        )
        report.document_reports.append(doc_report)

        quality_status = doc_report.quality_gate_status
        if quality_status == "FAIL":
            if config.strict_quality_gate:
                report.errors.append(
                    f"Quality gate FAIL for document {document_id}; original pipeline blocked."
                )
            else:
                report.fallback_used = True
                report.warnings.append(
                    f"Quality gate FAIL for document {document_id}; falling back to original pipeline."
                )
        elif quality_status not in config.allowed_quality_gate_status:
            report.warnings.append(
                f"Quality gate {quality_status} for document {document_id} is outside allowed statuses."
            )

    _finalize_report(report)
    return report


def _document_report_from_payload(
    payload: DslAwareIngestionPayload,
    document_id: str,
    file_path: str | None,
    dsl_path: Path,
    generate_mapping_plan: bool,
) -> DslAwarePipelineDocumentReport:
    summary = payload.summary
    quality_metrics = summary.get("qualityMetrics", {})
    quality_gate = summary.get("qualityGate", {})
    integration_readiness = summary.get("integrationReadiness", {})

    return DslAwarePipelineDocumentReport(
        document_id=document_id,
        file_path=file_path,
        dsl_path=str(dsl_path),
        dsl_found=True,
        payload_built=True,
        quality_gate_status=quality_gate.get("status"),
        recommended_next_step=integration_readiness.get("recommendedNextStep"),
        vector_payload_count=summary.get("vectorPayloadCount", 0),
        extraction_payload_count=summary.get("extractionPayloadCount", 0),
        metadata_payload_count=summary.get("metadataPayloadCount", 0),
        source_text_unit_count=summary.get("sourceTextUnitCount", 0),
        dsl_aware_chunk_count=summary.get("dslAwareChunkCount", 0),
        candidate_warn_count=quality_metrics.get("candidateWarnCount", 0),
        candidate_warn_ratio=quality_metrics.get("candidateWarnRatio", 0.0),
        unmapped_ratio=quality_metrics.get("unmappedRatio", 0.0),
        unknown_ratio=quality_metrics.get("unknownRatio", 0.0),
        write_stores=summary.get("writeStores", False),
        quality_metrics=quality_metrics,
        quality_gate=quality_gate,
        integration_readiness=integration_readiness,
        pipeline_mapping_plan=_pipeline_mapping_plan(payload)
        if generate_mapping_plan
        else None,
    )


def _pipeline_mapping_plan(payload: DslAwareIngestionPayload) -> dict[str, Any]:
    return serialize_pipeline_mapping_plan(build_pipeline_mapping_plan(payload))


def _should_call_original(
    report: DslAwarePipelineHookReport,
    config: DslAwarePipelineHookConfig,
) -> bool:
    if config.dry_run_only:
        return False
    if not config.fallback_to_original:
        return False
    if config.strict_quality_gate and any(
        doc.quality_gate_status == "FAIL" for doc in report.document_reports
    ):
        return False
    return True


def _empty_report(
    config: DslAwarePipelineHookConfig,
    original_pipeline_called: bool,
) -> DslAwarePipelineHookReport:
    report = DslAwarePipelineHookReport(
        enabled=False,
        dry_run=config.dry_run,
        dry_run_only=config.dry_run_only,
        original_pipeline_called=original_pipeline_called,
        fallback_used=False,
    )
    _finalize_report(report)
    return report


def _finalize_report(report: DslAwarePipelineHookReport) -> None:
    report.summary = {
        "documentCount": len(report.document_reports),
        "payloadBuiltCount": sum(
            1 for doc_report in report.document_reports if doc_report.payload_built
        ),
        "dslFoundCount": sum(
            1 for doc_report in report.document_reports if doc_report.dsl_found
        ),
        "qualityGateDistribution": _quality_gate_distribution(
            report.document_reports
        ),
        "candidateWarnCount": sum(
            doc_report.candidate_warn_count for doc_report in report.document_reports
        ),
        "vectorPayloadCount": sum(
            doc_report.vector_payload_count for doc_report in report.document_reports
        ),
        "extractionPayloadCount": sum(
            doc_report.extraction_payload_count
            for doc_report in report.document_reports
        ),
        "metadataPayloadCount": sum(
            doc_report.metadata_payload_count for doc_report in report.document_reports
        ),
        "writeStores": False,
        "featureFlagName": FEATURE_FLAG_NAME,
        "defaultEnabled": False,
        "supportsFallbackToOriginalPipeline": True,
        "recommendedFallback": "original_lightrag_pipeline",
    }


def _quality_gate_distribution(
    document_reports: list[DslAwarePipelineDocumentReport],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for doc_report in document_reports:
        status = doc_report.quality_gate_status or "NOT_BUILT"
        result[status] = result.get(status, 0) + 1
    return dict(sorted(result.items()))


def _write_report_if_needed(
    report: DslAwarePipelineHookReport,
    config: DslAwarePipelineHookConfig,
    track_id: str | None,
) -> None:
    if not config.report_dir:
        return
    report_dir = Path(config.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_id = track_id or _first_report_document_id(report) or "no_document"
    report_path = report_dir / f"dsl_aware_dry_run_{_safe_filename(report_id)}.json"
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _first_report_document_id(report: DslAwarePipelineHookReport) -> str | None:
    if not report.document_reports:
        return None
    return report.document_reports[0].document_id


def _wrapper_result(
    report: DslAwarePipelineHookReport,
    original_result,
) -> dict[str, Any]:
    return {
        "dslAwareHookReport": report.to_dict(),
        "originalResult": original_result,
    }


def _normalize_dsl_paths(
    dsl_paths,
    count: int,
) -> tuple[list[str | None], dict | None]:
    if isinstance(dsl_paths, dict):
        return [None] * count, dsl_paths
    return _normalize_optional_list(dsl_paths, count), None


def _normalize_optional_list(value, count: int) -> list:
    if isinstance(value, list):
        if len(value) != count:
            raise ValueError(f"Expected {count} values, got {len(value)}")
        return value
    if value is None:
        return [None] * count
    if count == 1:
        return [value]
    return [value for _ in range(count)]


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def _document_id(id_value, file_path: str | None, index: int) -> str:
    if id_value is not None:
        return str(id_value)
    if file_path:
        return Path(file_path).stem
    return f"document_{index + 1}"


def _existing_path(value) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path if path.exists() else None


def _safe_filename(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in value
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
