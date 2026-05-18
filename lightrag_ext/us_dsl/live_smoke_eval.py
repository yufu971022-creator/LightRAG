from __future__ import annotations

import asyncio
import inspect
import os
from dataclasses import dataclass, field
from typing import Any

from lightrag.prompt import PROMPTS

from .extraction_eval import ExtractionInputPair
from .extraction_metrics import (
    ExtractionComparisonMetrics,
    ExtractionRunResult,
    compare_extraction_results,
    parse_tuple_extraction_output,
)
from .prompt_selector import select_continue_prompt, select_extraction_prompts


LIVE_EXTRACTION_ENV = "LIGHTRAG_DSL_RUN_LIVE_EXTRACTION"
MAX_OUTPUT_TOKENS_ENV = "LIGHTRAG_DSL_LIVE_SMOKE_MAX_TOKENS"
DEFAULT_MAX_SAMPLES = 6
DEFAULT_MAX_GLEANING_SAMPLES = 2
MAX_LIVE_SMOKE_SAMPLES = 10
MAX_LIVE_SMOKE_GLEANING_SAMPLES = 3
DEFAULT_MAX_OUTPUT_TOKENS = 3000

PRODUCT_DESIGN_ENTITY_TYPES = {
    "FieldSpec",
    "StateTransition",
    "TaskRule",
    "BackendApi",
    "AuditLog",
    "MigrationTask",
    "DfxControl",
    "ReportFilter",
    "ApprovalAction",
}
PRODUCT_DESIGN_RELATION_TYPES = {
    "HasFieldSpec",
    "GeneratesTask",
    "CallsBackendApi",
    "WritesAuditLog",
    "TransitionsTo",
    "RequiresPermission",
    "MapsToColumn",
    "RequiresIdempotency",
}
GENERIC_TEXT_SAMPLES = [
    {
        "sample_id": "generic-company-office",
        "text": (
            "Acme Corporation opened a new regional office in Singapore this week. "
            "The company said the office will support local hiring and customer service."
        ),
        "evidence_keywords": ["Acme Corporation", "Singapore", "regional office"],
    },
    {
        "sample_id": "generic-cloud-computing",
        "text": (
            "Cloud computing lets organizations rent computing resources on demand. "
            "Common benefits include scalability, elasticity, and reduced hardware maintenance."
        ),
        "evidence_keywords": ["Cloud computing", "scalability", "elasticity"],
    },
]


@dataclass(frozen=True)
class LiveSmokeSample:
    sample_id: str
    sample_kind: str
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str
    baseline_input: str
    dsl_aware_input: str | None
    allowed_entity_types: list[str]
    allowed_relation_types: list[str]
    expected_entities: list[dict[str, Any]]
    expected_relations: list[dict[str, Any]]
    evidence_keywords: list[str]


@dataclass(frozen=True)
class GenericPromptImpactMetrics:
    sample_id: str
    entity_count: int
    relation_count: int
    parse_success: bool
    product_design_entity_over_extraction_count: int
    product_design_relation_over_extraction_count: int
    generic_text_over_productized: bool
    parse_errors: list[str]


@dataclass(frozen=True)
class LiveSmokeSampleMetric:
    sample_id: str
    sample_kind: str
    parse_success_baseline: bool
    parse_success_dsl_aware: bool | None
    baseline_raw_output: str = ""
    dsl_aware_raw_output: str | None = None
    baseline_parse_errors: list[str] = field(default_factory=list)
    dsl_aware_parse_errors: list[str] = field(default_factory=list)
    comparison: ExtractionComparisonMetrics | None = None
    generic_impact: GenericPromptImpactMetrics | None = None


@dataclass
class LiveSmokeReport:
    live_llm_used: bool
    skipped: bool
    skip_reason: str | None
    sample_count: int
    dsl_aware_sample_count: int
    product_plain_sample_count: int
    generic_sample_count: int
    parse_success_rate_baseline: float
    parse_success_rate_dsl_aware: float
    dsl_aware_improved_count: int
    dsl_aware_degraded_count: int
    generic_over_productized_count: int
    live_llm_error_count: int
    tuple_format_violation_count: int
    completion_delimiter_missing_count: int
    incomplete_tuple_count: int
    max_output_tokens: int
    output_truncated_suspected_count: int
    field_table_tuple_violation_count: int
    gleaning_duplicate_count: int
    gleaning_new_record_count: int
    gleaning_parse_success_rate: float
    metrics: list[LiveSmokeSampleMetric]
    aggregate_summary: dict[str, Any]
    recommended_next_step: str
    risks: list[str] = field(default_factory=list)
    fake_mode: bool = False
    gleaning_summary: dict[str, Any] | None = None


def live_smoke_enabled() -> bool:
    return os.getenv(LIVE_EXTRACTION_ENV) == "1"


def build_live_smoke_samples(
    input_pairs: list[ExtractionInputPair],
    *,
    max_samples: int = DEFAULT_MAX_SAMPLES,
) -> list[LiveSmokeSample]:
    max_samples = max(0, max_samples)
    if max_samples == 0:
        return []

    dsl_budget = max(1, max_samples - 2) if input_pairs else 0
    dsl_pairs = input_pairs[: min(dsl_budget, len(input_pairs))]
    samples = [_dsl_sample(pair) for pair in dsl_pairs]

    if len(samples) < max_samples and input_pairs:
        plain_source = input_pairs[min(len(dsl_pairs), len(input_pairs) - 1)]
        samples.append(_plain_product_sample(plain_source))

    for generic in GENERIC_TEXT_SAMPLES:
        if len(samples) >= max_samples:
            break
        samples.append(_generic_sample(generic))

    return samples[:max_samples]


def run_live_extraction_smoke(
    input_pairs: list[ExtractionInputPair],
    llm_callable=None,
    *,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    run_gleaning: bool = False,
    max_gleaning_samples: int = DEFAULT_MAX_GLEANING_SAMPLES,
    max_output_tokens: int | None = None,
) -> LiveSmokeReport:
    return asyncio.run(
        arun_live_extraction_smoke(
            input_pairs,
            llm_callable=llm_callable,
            max_samples=max_samples,
            run_gleaning=run_gleaning,
            max_gleaning_samples=max_gleaning_samples,
            max_output_tokens=max_output_tokens,
        )
    )


async def arun_live_extraction_smoke(
    input_pairs: list[ExtractionInputPair],
    llm_callable=None,
    *,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    run_gleaning: bool = False,
    max_gleaning_samples: int = DEFAULT_MAX_GLEANING_SAMPLES,
    max_output_tokens: int | None = None,
) -> LiveSmokeReport:
    if llm_callable is None:
        if not live_smoke_enabled():
            return _skipped_report(
                "Set LIGHTRAG_DSL_RUN_LIVE_EXTRACTION=1 and provide llm_callable to run live smoke."
            )
        return _skipped_report("No llm_callable was provided for live smoke.")

    metrics: list[LiveSmokeSampleMetric] = []
    risks: list[str] = []
    if max_samples > MAX_LIVE_SMOKE_SAMPLES:
        risks.append(
            f"max_samples capped from {max_samples} to {MAX_LIVE_SMOKE_SAMPLES}."
        )
        max_samples = MAX_LIVE_SMOKE_SAMPLES
    if max_gleaning_samples > MAX_LIVE_SMOKE_GLEANING_SAMPLES:
        risks.append(
            "max_gleaning_samples capped from "
            f"{max_gleaning_samples} to {MAX_LIVE_SMOKE_GLEANING_SAMPLES}."
        )
        max_gleaning_samples = MAX_LIVE_SMOKE_GLEANING_SAMPLES
    max_output_tokens = max_output_tokens or _configured_max_output_tokens()

    samples = build_live_smoke_samples(input_pairs, max_samples=max_samples)
    dsl_improved = 0
    dsl_degraded = 0
    generic_over_productized = 0
    live_llm_error_count = 0
    baseline_parse_success = 0
    dsl_parse_success = 0
    dsl_total = 0

    for sample in samples:
        baseline_result, baseline_error = await _run_single_extraction_safe(
            llm_callable,
            sample,
            mode="baseline",
            input_text=sample.baseline_input,
        )
        live_llm_error_count += int(baseline_error is not None)
        baseline_ok = _parse_success(baseline_result)
        baseline_parse_success += int(baseline_ok)

        if sample.sample_kind == "dsl_aware_product_design":
            dsl_total += 1
            dsl_result, dsl_error = await _run_single_extraction_safe(
                llm_callable,
                sample,
                mode="dsl_aware",
                input_text=sample.dsl_aware_input or sample.baseline_input,
            )
            live_llm_error_count += int(dsl_error is not None)
            dsl_ok = _parse_success(dsl_result)
            dsl_parse_success += int(dsl_ok)
            comparison = compare_extraction_results(
                sample_id=sample.sample_id,
                domain_code=sample.domain_code or "",
                section_type=sample.section_type,
                allowed_entity_types=sample.allowed_entity_types,
                allowed_relation_types=sample.allowed_relation_types,
                expected_entities=sample.expected_entities,
                expected_relations=sample.expected_relations,
                evidence_keywords=sample.evidence_keywords,
                baseline_result=baseline_result,
                dsl_result=dsl_result,
            )
            dsl_improved += int(comparison.improvement_label == "IMPROVED")
            dsl_degraded += int(comparison.improvement_label == "DEGRADED")
            metrics.append(
                LiveSmokeSampleMetric(
                    sample_id=sample.sample_id,
                    sample_kind=sample.sample_kind,
                    parse_success_baseline=baseline_ok,
                    parse_success_dsl_aware=dsl_ok,
                    baseline_raw_output=baseline_result.raw_output,
                    dsl_aware_raw_output=dsl_result.raw_output,
                    baseline_parse_errors=baseline_result.parse_errors,
                    dsl_aware_parse_errors=dsl_result.parse_errors,
                    comparison=comparison,
                )
            )
        elif sample.sample_kind == "generic_text":
            generic_impact = _generic_impact(sample.sample_id, baseline_result)
            generic_over_productized += int(
                generic_impact.generic_text_over_productized
            )
            metrics.append(
                LiveSmokeSampleMetric(
                    sample_id=sample.sample_id,
                    sample_kind=sample.sample_kind,
                    parse_success_baseline=baseline_ok,
                    parse_success_dsl_aware=None,
                    baseline_raw_output=baseline_result.raw_output,
                    baseline_parse_errors=baseline_result.parse_errors,
                    generic_impact=generic_impact,
                )
            )
        else:
            metrics.append(
                LiveSmokeSampleMetric(
                    sample_id=sample.sample_id,
                    sample_kind=sample.sample_kind,
                    parse_success_baseline=baseline_ok,
                    parse_success_dsl_aware=None,
                    baseline_raw_output=baseline_result.raw_output,
                    baseline_parse_errors=baseline_result.parse_errors,
                )
            )

    sample_count = len(samples)
    parse_success_rate_baseline = baseline_parse_success / sample_count if sample_count else 0.0
    parse_success_rate_dsl = dsl_parse_success / dsl_total if dsl_total else 0.0
    completion_delimiter_missing_count = _completion_delimiter_missing_count(metrics)
    incomplete_tuple_count = _incomplete_tuple_count(metrics)
    output_truncated_suspected_count = _output_truncated_suspected_count(metrics)
    tuple_format_violation_count = _tuple_format_violation_count(
        metrics,
        completion_delimiter_missing_count=completion_delimiter_missing_count,
        incomplete_tuple_count=incomplete_tuple_count,
    )
    field_table_tuple_violation_count = _field_table_tuple_violation_count(metrics)
    risks.extend(
        _risks(
            metrics,
            parse_success_rate_baseline,
            parse_success_rate_dsl,
            tuple_format_violation_count=tuple_format_violation_count,
        )
    )
    if live_llm_error_count:
        risks.append("At least one live LLM call failed.")
    recommended = _recommended_next_step(
        skipped=False,
        dsl_total=dsl_total,
        improved=dsl_improved,
        degraded=dsl_degraded,
        generic_over_productized=generic_over_productized,
        parse_success_rate_baseline=parse_success_rate_baseline,
        parse_success_rate_dsl=parse_success_rate_dsl,
        tuple_format_violation_count=tuple_format_violation_count,
    )
    gleaning_summary = None
    gleaning_duplicate_count = 0
    gleaning_new_record_count = 0
    gleaning_parse_success_rate = 0.0
    if run_gleaning:
        successful_dsl_sample_ids = {
            metric.sample_id
            for metric in metrics
            if metric.sample_kind == "dsl_aware_product_design"
            and metric.parse_success_dsl_aware is True
        }
        gleaning_summary = await _run_gleaning_smoke(
            llm_callable,
            samples,
            max_gleaning_samples=max_gleaning_samples,
            successful_sample_ids=successful_dsl_sample_ids,
        )
        gleaning_duplicate_count = int(gleaning_summary["duplicateCount"])
        gleaning_new_record_count = int(gleaning_summary["newRecordCount"])
        gleaning_parse_success_rate = float(gleaning_summary["parseSuccessRate"])

    aggregate_summary = {
        "sample_count": sample_count,
        "dsl_aware_improved_count": dsl_improved,
        "dsl_aware_degraded_count": dsl_degraded,
        "generic_over_productized_count": generic_over_productized,
        "live_llm_error_count": live_llm_error_count,
        "tuple_format_violation_count": tuple_format_violation_count,
        "completion_delimiter_missing_count": completion_delimiter_missing_count,
        "incomplete_tuple_count": incomplete_tuple_count,
        "max_output_tokens": max_output_tokens,
        "output_truncated_suspected_count": output_truncated_suspected_count,
        "field_table_tuple_violation_count": field_table_tuple_violation_count,
        "gleaning_duplicate_count": gleaning_duplicate_count,
        "gleaning_new_record_count": gleaning_new_record_count,
        "gleaning_parse_success_rate": gleaning_parse_success_rate,
        "parse_success_rate_baseline": parse_success_rate_baseline,
        "parse_success_rate_dsl_aware": parse_success_rate_dsl,
        "recommended_next_step": recommended,
    }

    return LiveSmokeReport(
        live_llm_used=True,
        skipped=False,
        skip_reason=None,
        sample_count=sample_count,
        dsl_aware_sample_count=dsl_total,
        product_plain_sample_count=sum(
            1 for sample in samples if sample.sample_kind == "plain_product_design"
        ),
        generic_sample_count=sum(
            1 for sample in samples if sample.sample_kind == "generic_text"
        ),
        parse_success_rate_baseline=parse_success_rate_baseline,
        parse_success_rate_dsl_aware=parse_success_rate_dsl,
        dsl_aware_improved_count=dsl_improved,
        dsl_aware_degraded_count=dsl_degraded,
        generic_over_productized_count=generic_over_productized,
        live_llm_error_count=live_llm_error_count,
        tuple_format_violation_count=tuple_format_violation_count,
        completion_delimiter_missing_count=completion_delimiter_missing_count,
        incomplete_tuple_count=incomplete_tuple_count,
        max_output_tokens=max_output_tokens,
        output_truncated_suspected_count=output_truncated_suspected_count,
        field_table_tuple_violation_count=field_table_tuple_violation_count,
        gleaning_duplicate_count=gleaning_duplicate_count,
        gleaning_new_record_count=gleaning_new_record_count,
        gleaning_parse_success_rate=gleaning_parse_success_rate,
        metrics=metrics,
        aggregate_summary=aggregate_summary,
        recommended_next_step=recommended,
        risks=risks,
        fake_mode=not live_smoke_enabled(),
        gleaning_summary=gleaning_summary,
    )


def build_extraction_prompts(
    input_text: str,
    *,
    entity_types: list[str],
    language: str = "English",
) -> tuple[str, str]:
    selection = select_extraction_prompts(
        input_text,
        entity_types=entity_types,
        language=language,
    )
    return selection.system_prompt, selection.user_prompt


def build_gleaning_prompt(
    *,
    entity_types: list[str],
    input_text: str = "",
    language: str = "English",
) -> str:
    selection = select_continue_prompt(
        input_text,
        entity_types=entity_types,
        language=language,
    )
    return selection.continue_prompt


def serialize_live_smoke_report(
    report: LiveSmokeReport,
    *,
    include_raw_output: bool = True,
) -> dict[str, Any]:
    return {
        "live_llm_used": report.live_llm_used,
        "skipped": report.skipped,
        "skip_reason": report.skip_reason,
        "sample_count": report.sample_count,
        "dsl_aware_sample_count": report.dsl_aware_sample_count,
        "product_plain_sample_count": report.product_plain_sample_count,
        "generic_sample_count": report.generic_sample_count,
        "parse_success_rate_baseline": report.parse_success_rate_baseline,
        "parse_success_rate_dsl_aware": report.parse_success_rate_dsl_aware,
        "dsl_aware_improved_count": report.dsl_aware_improved_count,
        "dsl_aware_degraded_count": report.dsl_aware_degraded_count,
        "generic_over_productized_count": report.generic_over_productized_count,
        "live_llm_error_count": report.live_llm_error_count,
        "tuple_format_violation_count": report.tuple_format_violation_count,
        "completion_delimiter_missing_count": report.completion_delimiter_missing_count,
        "incomplete_tuple_count": report.incomplete_tuple_count,
        "max_output_tokens": report.max_output_tokens,
        "output_truncated_suspected_count": report.output_truncated_suspected_count,
        "field_table_tuple_violation_count": report.field_table_tuple_violation_count,
        "gleaning_duplicate_count": report.gleaning_duplicate_count,
        "gleaning_new_record_count": report.gleaning_new_record_count,
        "gleaning_parse_success_rate": report.gleaning_parse_success_rate,
        "recommended_next_step": report.recommended_next_step,
        "risks": report.risks,
        "fake_mode": report.fake_mode,
        "gleaning_smoke_summary": report.gleaning_summary,
        "aggregate_summary": report.aggregate_summary,
        "metrics": [
            _serialize_metric(metric, include_raw_output=include_raw_output)
            for metric in report.metrics
        ],
    }


async def _run_single_extraction(
    llm_callable,
    sample: LiveSmokeSample,
    *,
    mode: str,
    input_text: str,
    history_messages: list[dict[str, str]] | None = None,
) -> ExtractionRunResult:
    system_prompt, user_prompt = build_extraction_prompts(
        input_text,
        entity_types=sample.allowed_entity_types,
    )
    raw_output = await _call_llm(
        llm_callable,
        user_prompt,
        system_prompt=system_prompt,
        history_messages=history_messages,
        sample=sample,
        extraction_mode=mode,
    )
    return parse_tuple_extraction_output(
        _response_text(raw_output),
        sample_id=sample.sample_id,
        mode=mode,
        allowed_relation_types=sample.allowed_relation_types,
    )


async def _run_single_extraction_safe(
    llm_callable,
    sample: LiveSmokeSample,
    *,
    mode: str,
    input_text: str,
    history_messages: list[dict[str, str]] | None = None,
) -> tuple[ExtractionRunResult, str | None]:
    try:
        result = await _run_single_extraction(
            llm_callable,
            sample,
            mode=mode,
            input_text=input_text,
            history_messages=history_messages,
        )
        return result, None
    except Exception as exc:
        return (
            ExtractionRunResult(
                sample_id=sample.sample_id,
                mode=mode,
                entities=[],
                relations=[],
                raw_output="",
                parse_errors=[f"LLM_CALL_ERROR: {exc.__class__.__name__}: {exc}"],
            ),
            str(exc),
        )


async def _run_gleaning_smoke(
    llm_callable,
    samples: list[LiveSmokeSample],
    *,
    max_gleaning_samples: int,
    successful_sample_ids: set[str],
) -> dict[str, Any]:
    targets = [
        sample
        for sample in samples
        if sample.sample_kind == "dsl_aware_product_design"
        and sample.sample_id in successful_sample_ids
    ][:max_gleaning_samples]
    results = []
    for sample in targets:
        initial, initial_error = await _run_single_extraction_safe(
            llm_callable,
            sample,
            mode="dsl_aware",
            input_text=sample.dsl_aware_input or sample.baseline_input,
        )
        if initial_error:
            results.append(
                {
                    "sampleId": sample.sample_id,
                    "parseSuccess": False,
                    "newEntityCount": 0,
                    "newRelationCount": 0,
                    "duplicateCount": 0,
                    "duplicateEntityCount": 0,
                    "duplicateRelationCount": 0,
                    "parseErrorCount": len(initial.parse_errors),
                    "jsonViolationCount": 0,
                    "explanationViolationCount": 0,
                }
            )
            continue
        system_prompt, _ = build_extraction_prompts(
            sample.dsl_aware_input or sample.baseline_input,
            entity_types=sample.allowed_entity_types,
        )
        glean_prompt = build_gleaning_prompt(
            entity_types=sample.allowed_entity_types,
            input_text=sample.dsl_aware_input or sample.baseline_input,
        )
        raw = await _call_llm(
            llm_callable,
            glean_prompt,
            system_prompt=system_prompt,
            history_messages=[
                {"role": "assistant", "content": initial.raw_output},
            ],
            sample=sample,
            extraction_mode="gleaning",
        )
        glean = parse_tuple_extraction_output(
            _response_text(raw),
            sample_id=sample.sample_id,
            mode="gleaning",
            allowed_relation_types=sample.allowed_relation_types,
        )
        raw_text = _response_text(raw)
        parse_success = _parse_success(glean) or _gleaning_empty_success(raw_text, glean)
        results.append(
            {
                "sampleId": sample.sample_id,
                "parseSuccess": parse_success,
                "newEntityCount": len(glean.entities),
                "newRelationCount": len(glean.relations),
                "duplicateCount": _duplicate_count(initial, glean),
                "duplicateEntityCount": _duplicate_entity_count(initial, glean),
                "duplicateRelationCount": _duplicate_relation_count(initial, glean),
                "parseErrorCount": len(glean.parse_errors),
                "jsonViolationCount": int("{" in raw_text or "```json" in raw_text),
                "explanationViolationCount": int(
                    raw_text.strip().lower().startswith(("here", "sure", "these"))
                ),
            }
        )
    parse_success_count = sum(1 for item in results if item["parseSuccess"])
    new_record_count = sum(
        item["newEntityCount"] + item["newRelationCount"] for item in results
    )
    return {
        "enabled": True,
        "sampleCount": len(targets),
        "gleaning_sample_count": len(targets),
        "parseSuccessRate": parse_success_count / len(targets) if targets else 0.0,
        "gleaning_parse_success_rate": parse_success_count / len(targets)
        if targets
        else 0.0,
        "duplicateCount": sum(item["duplicateCount"] for item in results),
        "gleaning_duplicate_count": sum(item["duplicateCount"] for item in results),
        "newRecordCount": new_record_count,
        "gleaning_new_record_count": new_record_count,
        "jsonViolationCount": sum(item["jsonViolationCount"] for item in results),
        "gleaning_json_violation_count": sum(
            item["jsonViolationCount"] for item in results
        ),
        "explanationViolationCount": sum(
            item["explanationViolationCount"] for item in results
        ),
        "gleaning_explanation_violation_count": sum(
            item["explanationViolationCount"] for item in results
        ),
        "results": results,
    }


async def _call_llm(
    llm_callable,
    user_prompt: str,
    *,
    system_prompt: str,
    history_messages: list[dict[str, str]] | None,
    sample: LiveSmokeSample,
    extraction_mode: str,
):
    try:
        result = llm_callable(
            user_prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            sample=sample,
            extraction_mode=extraction_mode,
        )
    except TypeError:
        result = llm_callable(
            user_prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
        )
    if inspect.isawaitable(result):
        result = await result
    return result


def _response_text(response) -> str:
    if isinstance(response, tuple):
        return str(response[0])
    return str(response)


def _serialize_metric(
    metric: LiveSmokeSampleMetric,
    *,
    include_raw_output: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sample_id": metric.sample_id,
        "sample_type": metric.sample_kind,
        "parse_success_baseline": metric.parse_success_baseline,
        "parse_success_dsl_aware": metric.parse_success_dsl_aware,
        "baseline_parse_errors": metric.baseline_parse_errors,
        "dsl_aware_parse_errors": metric.dsl_aware_parse_errors,
    }
    if include_raw_output:
        result["baseline_raw_output"] = metric.baseline_raw_output
        result["dsl_aware_raw_output"] = metric.dsl_aware_raw_output
    if metric.comparison is not None:
        comparison = metric.comparison
        result.update(
            {
                "domain_code": comparison.domain_code,
                "section_type": comparison.section_type,
                "baseline_entity_count": comparison.baseline_entity_count,
                "dsl_entity_count": comparison.dsl_entity_count,
                "baseline_relation_count": comparison.baseline_relation_count,
                "dsl_relation_count": comparison.dsl_relation_count,
                "baseline_allowed_entity_type_hit_rate": comparison.baseline_allowed_entity_type_hit_rate,
                "dsl_allowed_entity_type_hit_rate": comparison.dsl_allowed_entity_type_hit_rate,
                "baseline_allowed_relation_type_hit_rate": comparison.baseline_allowed_relation_type_hit_rate,
                "dsl_allowed_relation_type_hit_rate": comparison.dsl_allowed_relation_type_hit_rate,
                "baseline_invalid_entity_type_count": comparison.baseline_invalid_entity_type_count,
                "dsl_invalid_entity_type_count": comparison.dsl_invalid_entity_type_count,
                "baseline_invalid_relation_type_count": comparison.baseline_invalid_relation_type_count,
                "dsl_invalid_relation_type_count": comparison.dsl_invalid_relation_type_count,
                "baseline_snake_case_relation_count": comparison.baseline_snake_case_relation_count,
                "dsl_snake_case_relation_count": comparison.dsl_snake_case_relation_count,
                "baseline_candidate_relation_count": comparison.baseline_candidate_relation_count,
                "dsl_candidate_relation_count": comparison.dsl_candidate_relation_count,
                "evidence_keyword_coverage_delta": comparison.evidence_keyword_coverage_delta,
                "improvement_label": comparison.improvement_label,
                "reasons": comparison.reasons,
            }
        )
    if metric.generic_impact is not None:
        generic = metric.generic_impact
        result.update(
            {
                "product_design_entity_over_extraction_count": generic.product_design_entity_over_extraction_count,
                "product_design_relation_over_extraction_count": generic.product_design_relation_over_extraction_count,
                "generic_text_over_productized": generic.generic_text_over_productized,
            }
        )
    return result


def _skipped_report(skip_reason: str) -> LiveSmokeReport:
    return LiveSmokeReport(
        live_llm_used=False,
        skipped=True,
        skip_reason=skip_reason,
        sample_count=0,
        dsl_aware_sample_count=0,
        product_plain_sample_count=0,
        generic_sample_count=0,
        parse_success_rate_baseline=0.0,
        parse_success_rate_dsl_aware=0.0,
        dsl_aware_improved_count=0,
        dsl_aware_degraded_count=0,
        generic_over_productized_count=0,
        live_llm_error_count=0,
        tuple_format_violation_count=0,
        completion_delimiter_missing_count=0,
        incomplete_tuple_count=0,
        max_output_tokens=_configured_max_output_tokens(),
        output_truncated_suspected_count=0,
        field_table_tuple_violation_count=0,
        gleaning_duplicate_count=0,
        gleaning_new_record_count=0,
        gleaning_parse_success_rate=0.0,
        metrics=[],
        aggregate_summary={},
        recommended_next_step="RUN_LIVE_SMOKE_WITH_LLM_CONFIG",
        risks=[skip_reason],
    )


def _generic_impact(
    sample_id: str,
    result: ExtractionRunResult,
) -> GenericPromptImpactMetrics:
    product_entity_count = sum(
        1 for entity in result.entities if entity.entity_type in PRODUCT_DESIGN_ENTITY_TYPES
    )
    product_relation_count = sum(
        1
        for relation in result.relations
        if relation.relation_type in PRODUCT_DESIGN_RELATION_TYPES
        or any(
            relation_type in relation.relationship_keywords
            for relation_type in PRODUCT_DESIGN_RELATION_TYPES
        )
    )
    return GenericPromptImpactMetrics(
        sample_id=sample_id,
        entity_count=len(result.entities),
        relation_count=len(result.relations),
        parse_success=_parse_success(result),
        product_design_entity_over_extraction_count=product_entity_count,
        product_design_relation_over_extraction_count=product_relation_count,
        generic_text_over_productized=product_entity_count > 0
        or product_relation_count > 0,
        parse_errors=result.parse_errors,
    )


def _parse_success(result: ExtractionRunResult) -> bool:
    return bool(result.entities or result.relations) and not result.parse_errors


def _tuple_format_violation_count(
    metrics: list[LiveSmokeSampleMetric],
    *,
    completion_delimiter_missing_count: int,
    incomplete_tuple_count: int,
) -> int:
    parse_failure_count = 0
    for metric in metrics:
        parse_failure_count += int(not metric.parse_success_baseline)
        if metric.parse_success_dsl_aware is not None:
            parse_failure_count += int(not metric.parse_success_dsl_aware)
    return max(
        parse_failure_count,
        completion_delimiter_missing_count,
        incomplete_tuple_count,
    )


def _completion_delimiter_missing_count(metrics: list[LiveSmokeSampleMetric]) -> int:
    return sum(
        1
        for output in _metric_outputs(metrics)
        if output.strip()
        and PROMPTS["DEFAULT_COMPLETION_DELIMITER"] not in output
    )


def _incomplete_tuple_count(metrics: list[LiveSmokeSampleMetric]) -> int:
    count = 0
    for metric in metrics:
        all_errors = [
            *metric.baseline_parse_errors,
            *metric.dsl_aware_parse_errors,
        ]
        count += sum(
            1
            for error in all_errors
            if "Malformed entity record" in error
            or "Malformed relation record" in error
            or "Unknown tuple record" in error
        )
    return count


def _output_truncated_suspected_count(metrics: list[LiveSmokeSampleMetric]) -> int:
    count = 0
    for output in _metric_outputs(metrics):
        stripped = output.strip()
        if not stripped:
            continue
        if PROMPTS["DEFAULT_COMPLETION_DELIMITER"] not in stripped:
            count += 1
            continue
        tail = stripped.rsplit(PROMPTS["DEFAULT_COMPLETION_DELIMITER"], 1)[0].strip()
        last_line = tail.splitlines()[-1].strip() if tail else ""
        if (
            last_line.startswith(("entity", "relation"))
            and last_line.count(PROMPTS["DEFAULT_TUPLE_DELIMITER"]) not in {3, 4}
        ):
            count += 1
    return count


def _field_table_tuple_violation_count(metrics: list[LiveSmokeSampleMetric]) -> int:
    count = 0
    for metric in metrics:
        if _metric_section_type(metric) != "field_table":
            continue
        count += int(not metric.parse_success_baseline)
        if metric.parse_success_dsl_aware is not None:
            count += int(not metric.parse_success_dsl_aware)
    return count


def _metric_outputs(metrics: list[LiveSmokeSampleMetric]) -> list[str]:
    outputs: list[str] = []
    for metric in metrics:
        if metric.baseline_raw_output:
            outputs.append(metric.baseline_raw_output)
        if metric.dsl_aware_raw_output:
            outputs.append(metric.dsl_aware_raw_output)
    return outputs


def _metric_section_type(metric: LiveSmokeSampleMetric) -> str | None:
    if metric.comparison is not None:
        return metric.comparison.section_type
    return None


def _risks(
    metrics: list[LiveSmokeSampleMetric],
    baseline_rate: float,
    dsl_rate: float,
    *,
    tuple_format_violation_count: int,
) -> list[str]:
    risks: list[str] = []
    if baseline_rate < 0.8 or dsl_rate < 0.8:
        risks.append("Tuple parse success rate is below the smoke threshold.")
    if tuple_format_violation_count:
        risks.append("Tuple output stability violations were detected.")
    if any(metric.generic_impact and metric.generic_impact.generic_text_over_productized for metric in metrics):
        risks.append("Generic text was over-productized by the global prompt.")
    if any(
        not metric.parse_success_baseline
        or metric.parse_success_dsl_aware is False
        for metric in metrics
    ):
        risks.append("At least one sample has tuple parse errors or empty output.")
    return risks


def _recommended_next_step(
    *,
    skipped: bool,
    dsl_total: int,
    improved: int,
    degraded: int,
    generic_over_productized: int,
    parse_success_rate_baseline: float,
    parse_success_rate_dsl: float,
    tuple_format_violation_count: int,
) -> str:
    if skipped:
        return "RUN_LIVE_SMOKE_WITH_LLM_CONFIG"
    if tuple_format_violation_count:
        return "FIX_TUPLE_OUTPUT_STABILITY"
    if parse_success_rate_baseline < 0.8 or parse_success_rate_dsl < 0.8:
        return "FIX_TUPLE_OUTPUT_STABILITY"
    if dsl_total and improved <= degraded:
        return "TUNE_DSL_CONTEXT_OR_PROMPT"
    if generic_over_productized:
        return "ADD_PROMPT_SELECTOR_BEFORE_EXTRACTION_HOOK"
    if dsl_total and improved > degraded:
        return "CONSIDER_EXTRACTION_HOOK_DRY_RUN"
    return "TUNE_DSL_CONTEXT_OR_PROMPT"


def _dsl_sample(pair: ExtractionInputPair) -> LiveSmokeSample:
    return LiveSmokeSample(
        sample_id=pair.sample_id,
        sample_kind="dsl_aware_product_design",
        source_us_id=pair.source_us_id,
        feature_key=pair.feature_key,
        domain_code=pair.domain_code,
        section_type=pair.section_type,
        baseline_input=pair.baseline_input,
        dsl_aware_input=pair.dsl_aware_input,
        allowed_entity_types=pair.allowed_entity_types,
        allowed_relation_types=pair.allowed_relation_types,
        expected_entities=pair.expected_entities,
        expected_relations=pair.expected_relations,
        evidence_keywords=pair.evidence_keywords,
    )


def _plain_product_sample(pair: ExtractionInputPair) -> LiveSmokeSample:
    return LiveSmokeSample(
        sample_id=f"plain-{pair.sample_id}",
        sample_kind="plain_product_design",
        source_us_id=pair.source_us_id,
        feature_key=pair.feature_key,
        domain_code=pair.domain_code,
        section_type=pair.section_type,
        baseline_input=pair.baseline_input,
        dsl_aware_input=None,
        allowed_entity_types=pair.allowed_entity_types,
        allowed_relation_types=pair.allowed_relation_types,
        expected_entities=pair.expected_entities,
        expected_relations=pair.expected_relations,
        evidence_keywords=pair.evidence_keywords,
    )


def _generic_sample(sample: dict[str, Any]) -> LiveSmokeSample:
    return LiveSmokeSample(
        sample_id=str(sample["sample_id"]),
        sample_kind="generic_text",
        source_us_id=None,
        feature_key=None,
        domain_code=None,
        section_type="generic_text",
        baseline_input=str(sample["text"]),
        dsl_aware_input=None,
        allowed_entity_types=[
            "Organization",
            "Location",
            "Concept",
            "Event",
            "CandidateEntity",
        ],
        allowed_relation_types=["RelatedTo", "CandidateRelation"],
        expected_entities=[],
        expected_relations=[],
        evidence_keywords=[
            value for value in sample.get("evidence_keywords", []) if isinstance(value, str)
        ],
    )


def _duplicate_entity_count(
    initial: ExtractionRunResult,
    glean: ExtractionRunResult,
) -> int:
    initial_names = {entity.entity_name for entity in initial.entities}
    return sum(1 for entity in glean.entities if entity.entity_name in initial_names)


def _duplicate_relation_count(
    initial: ExtractionRunResult,
    glean: ExtractionRunResult,
) -> int:
    initial_relations = {
        (
            relation.source_entity,
            relation.target_entity,
            relation.relationship_keywords,
        )
        for relation in initial.relations
    }
    return sum(
        1
        for relation in glean.relations
        if (
            relation.source_entity,
            relation.target_entity,
            relation.relationship_keywords,
        )
        in initial_relations
    )


def _duplicate_count(
    initial: ExtractionRunResult,
    glean: ExtractionRunResult,
) -> int:
    return _duplicate_entity_count(initial, glean) + _duplicate_relation_count(
        initial,
        glean,
    )


def _gleaning_empty_success(raw_text: str, result: ExtractionRunResult) -> bool:
    return (
        not result.parse_errors
        and raw_text.strip() == PROMPTS["DEFAULT_COMPLETION_DELIMITER"]
    )


def _configured_max_output_tokens() -> int:
    raw_value = os.getenv(MAX_OUTPUT_TOKENS_ENV)
    if raw_value is None:
        return DEFAULT_MAX_OUTPUT_TOKENS
    try:
        return int(raw_value)
    except ValueError:
        return DEFAULT_MAX_OUTPUT_TOKENS
