from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any

from lightrag.prompt import PROMPTS

from . import dsl_aware_prompts, generic_prompts, product_design_prompts
from .extraction_eval import (
    DEFAULT_PREFERRED_DOMAINS,
    DEFAULT_PREFERRED_SECTIONS,
    EVIDENCE_KEYWORDS,
    ExtractionInputPair,
    select_extraction_eval_samples,
)
from .extraction_metrics import (
    DEFAULT_COMPLETION_DELIMITER,
    DEFAULT_TUPLE_DELIMITER,
    ExtractionRunResult,
    is_snake_case_relation,
    parse_tuple_extraction_output,
)
from .payload_types import DslAwareIngestionPayload, ExtractionPayloadItem
from .prompt_selector import (
    PROMPT_MODE_DSL_AWARE,
    PROMPT_MODE_GENERIC,
    PROMPT_MODE_PRODUCT_DESIGN,
    PromptSelectorConfig,
    select_extraction_prompts,
)


FEATURE_FLAG_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_EXTRACT_ENTITIES_DRY_RUN"
LIVE_EXTRACTION_ENV = "LIGHTRAG_DSL_RUN_LIVE_EXTRACTION"
MAX_SAMPLES_ENV = "LIGHTRAG_DSL_EXTRACT_DRY_RUN_MAX_SAMPLES"
GLEANING_ENV = "LIGHTRAG_DSL_EXTRACT_DRY_RUN_GLEANING"
MAX_TOKENS_ENV = "LIGHTRAG_DSL_LIVE_SMOKE_MAX_TOKENS"

DEFAULT_MAX_SAMPLES = 6
HARD_MAX_SAMPLES = 10
DEFAULT_MAX_GLEANING_SAMPLES = 2
HARD_MAX_GLEANING_SAMPLES = 3


@dataclass(frozen=True)
class ExtractEntitiesDryRunConfig:
    enabled: bool = False
    dry_run: bool = True
    feature_flag_name: str = "enable_dsl_aware_extract_entities_dry_run"
    max_samples: int = DEFAULT_MAX_SAMPLES
    hard_max_samples: int = HARD_MAX_SAMPLES
    run_live_llm: bool = False
    run_gleaning: bool = False
    max_gleaning_samples: int = DEFAULT_MAX_GLEANING_SAMPLES
    hard_max_gleaning_samples: int = HARD_MAX_GLEANING_SAMPLES
    use_prompt_selector: bool = True
    use_native_extract_entities: bool = True
    strict_quality_gate: bool = False
    allowed_quality_gate_status: tuple[str, ...] = ("PASS", "WARN")
    fallback_to_eval_harness: bool = True
    max_tokens: int | None = None
    report_dir: str | None = None

    @classmethod
    def from_env(cls) -> "ExtractEntitiesDryRunConfig":
        return cls(
            enabled=os.getenv(FEATURE_FLAG_ENV) == "1",
            run_live_llm=os.getenv(LIVE_EXTRACTION_ENV) == "1",
            run_gleaning=os.getenv(GLEANING_ENV) == "1",
            max_samples=_env_int(MAX_SAMPLES_ENV, DEFAULT_MAX_SAMPLES),
            max_tokens=_optional_env_int(MAX_TOKENS_ENV),
        )


@dataclass(frozen=True)
class ExtractEntitiesDryRunSampleResult:
    sample_id: str
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str
    prompt_mode: str
    native_extract_called: bool
    parse_success: bool
    entity_count: int
    relation_count: int
    allowed_entity_type_hit_rate: float
    allowed_relation_type_hit_rate: float
    invalid_entity_type_count: int
    invalid_relation_type_count: int
    snake_case_relation_count: int
    candidate_entity_count: int
    candidate_relation_count: int
    raw_output_preview: str
    parse_errors: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    extracted_entities: list[dict[str, Any]] = field(default_factory=list)
    extracted_relations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExtractEntitiesDryRunReport:
    enabled: bool
    skipped: bool
    skip_reason: str | None
    native_extract_called: bool
    live_llm_used: bool
    sample_count: int
    baseline_sample_count: int
    dsl_aware_sample_count: int
    run_gleaning: bool
    prompt_selector_used: bool
    prompt_override_method: str
    storage_written: bool
    graph_merge_called: bool
    parser_modified: bool
    tuple_parse_success_rate: float
    dsl_aware_parse_success_rate: float
    entity_type_hit_rate: float
    relation_type_hit_rate: float
    invalid_entity_type_count: int
    invalid_relation_type_count: int
    snake_case_relation_count: int
    candidate_entity_count: int
    candidate_relation_count: int
    completion_delimiter_missing_count: int
    incomplete_tuple_count: int
    tuple_format_violation_count: int
    sample_results: list[ExtractEntitiesDryRunSampleResult] = field(default_factory=list)
    aggregate_summary: dict[str, Any] = field(default_factory=dict)
    recommended_next_step: str = ""
    risks: list[str] = field(default_factory=list)
    native_unsupported: bool = False
    prompt_override_restored: bool = True
    fallback_evaluator_called: bool = False


@dataclass
class InMemoryKVStorage:
    """Minimal async KV storage for tests; not used unless explicitly passed."""

    data: dict[str, dict[str, Any]] = field(default_factory=dict)
    upsert_count: int = 0
    delete_count: int = 0
    index_done_count: int = 0

    async def get_by_id(self, id: str) -> dict[str, Any] | None:
        return self.data.get(id)

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any] | None]:
        return [self.data.get(id) for id in ids]

    async def filter_keys(self, keys: set[str]) -> set[str]:
        return {key for key in keys if key not in self.data}

    async def upsert(self, data: dict[str, dict[str, Any]]) -> None:
        self.data.update(data)
        self.upsert_count += 1

    async def delete(self, ids: list[str]) -> None:
        for id in ids:
            self.data.pop(id, None)
        self.delete_count += 1

    async def is_empty(self) -> bool:
        return not self.data

    async def index_done_callback(self) -> None:
        self.index_done_count += 1


class _SimpleTokenizer:
    def encode(self, text: str) -> list[str]:
        return text.split()


@contextmanager
def temporary_prompt_overrides(
    *,
    mode: str,
    tuple_delimiter: str = DEFAULT_TUPLE_DELIMITER,
    completion_delimiter: str = DEFAULT_COMPLETION_DELIMITER,
):
    original = {
        "DEFAULT_TUPLE_DELIMITER": PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        "DEFAULT_COMPLETION_DELIMITER": PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
        "entity_extraction_system_prompt": PROMPTS["entity_extraction_system_prompt"],
        "entity_extraction_user_prompt": PROMPTS["entity_extraction_user_prompt"],
        "entity_continue_extraction_user_prompt": PROMPTS[
            "entity_continue_extraction_user_prompt"
        ],
        "entity_extraction_examples": PROMPTS["entity_extraction_examples"],
    }
    templates = _templates_for_mode(mode)
    try:
        PROMPTS["DEFAULT_TUPLE_DELIMITER"] = tuple_delimiter
        PROMPTS["DEFAULT_COMPLETION_DELIMITER"] = completion_delimiter
        PROMPTS["entity_extraction_system_prompt"] = templates["system"]
        PROMPTS["entity_extraction_user_prompt"] = templates["user"]
        PROMPTS["entity_continue_extraction_user_prompt"] = templates["continue"]
        PROMPTS["entity_extraction_examples"] = templates["examples"]
        yield
    finally:
        PROMPTS.update(original)


def run_extract_entities_dry_run_from_payload(
    payload: DslAwareIngestionPayload,
    *,
    llm_callable=None,
    config: ExtractEntitiesDryRunConfig | None = None,
) -> ExtractEntitiesDryRunReport:
    return asyncio.run(
        arun_extract_entities_dry_run_from_payload(
            payload,
            llm_callable=llm_callable,
            config=config,
        )
    )


async def arun_extract_entities_dry_run_from_payload(
    payload: DslAwareIngestionPayload,
    *,
    llm_callable=None,
    config: ExtractEntitiesDryRunConfig | None = None,
) -> ExtractEntitiesDryRunReport:
    config = config or ExtractEntitiesDryRunConfig()
    if not config.enabled:
        return _skipped_report(
            enabled=False,
            skip_reason="Feature flag enable_dsl_aware_extract_entities_dry_run is disabled.",
        )

    quality_gate_status = _quality_gate_status(payload)
    if quality_gate_status == "FAIL":
        return _skipped_report(
            enabled=True,
            skip_reason="Payload qualityGate.status is FAIL.",
            recommended_next_step="DO_NOT_CALL_NATIVE_EXTRACTION",
        )
    if (
        config.strict_quality_gate
        and quality_gate_status not in config.allowed_quality_gate_status
    ):
        return _skipped_report(
            enabled=True,
            skip_reason=f"Payload quality gate {quality_gate_status} is not allowed.",
            recommended_next_step="DO_NOT_CALL_NATIVE_EXTRACTION",
        )

    pairs = select_extraction_eval_samples(
        payload,
        max_samples=max(config.max_samples, config.hard_max_samples),
    )
    return await arun_native_extract_entities_dry_run(
        pairs,
        llm_callable=llm_callable,
        config=config,
    )


def run_native_extract_entities_dry_run(
    extraction_items: (
        DslAwareIngestionPayload
        | list[ExtractionInputPair]
        | list[ExtractionPayloadItem]
        | list[dict[str, Any]]
    ),
    *,
    llm_callable=None,
    config: ExtractEntitiesDryRunConfig | None = None,
) -> ExtractEntitiesDryRunReport:
    return asyncio.run(
        arun_native_extract_entities_dry_run(
            extraction_items,
            llm_callable=llm_callable,
            config=config,
        )
    )


async def arun_native_extract_entities_dry_run(
    extraction_items: (
        DslAwareIngestionPayload
        | list[ExtractionInputPair]
        | list[ExtractionPayloadItem]
        | list[dict[str, Any]]
    ),
    *,
    llm_callable=None,
    config: ExtractEntitiesDryRunConfig | None = None,
) -> ExtractEntitiesDryRunReport:
    config = config or ExtractEntitiesDryRunConfig()
    if not config.enabled:
        return _skipped_report(
            enabled=False,
            skip_reason="Feature flag enable_dsl_aware_extract_entities_dry_run is disabled.",
        )
    if config.run_live_llm and os.getenv(LIVE_EXTRACTION_ENV) != "1":
        return _skipped_report(
            enabled=True,
            skip_reason="Set LIGHTRAG_DSL_RUN_LIVE_EXTRACTION=1 to run live native extraction dry-run.",
        )
    pairs = _normalize_pairs(extraction_items)
    risks: list[str] = []
    pairs, cap_risks = _cap_pairs(pairs, config)
    risks.extend(cap_risks)

    if not config.use_native_extract_entities:
        return _unsupported_report("Native extract_entities use is disabled by config.")
    native_extract_entities, unsupported_reason = _resolve_native_extract_entities()
    if native_extract_entities is None:
        if config.fallback_to_eval_harness:
            return await _fallback_evaluator_report(
                pairs,
                reason=unsupported_reason or "Native extract_entities unavailable.",
                risks=risks,
                llm_callable=llm_callable,
            )
        return _unsupported_report(unsupported_reason or "Native extract_entities unavailable.")

    if config.run_gleaning and config.max_gleaning_samples > config.hard_max_gleaning_samples:
        risks.append(
            "max_gleaning_samples capped from "
            f"{config.max_gleaning_samples} to {config.hard_max_gleaning_samples}."
        )

    active_llm = llm_callable or _deterministic_native_llm
    call_recorder = _RecordingLlmCallable(active_llm, max_tokens=config.max_tokens)
    results: list[ExtractEntitiesDryRunSampleResult] = []
    prompt_restored = True

    for pair in pairs:
        selection = select_extraction_prompts(
            pair.dsl_aware_input,
            config=PromptSelectorConfig(),
            entity_types=pair.allowed_entity_types,
        )
        before_prompts = _prompt_snapshot()
        output_index = len(call_recorder.outputs)
        try:
            with temporary_prompt_overrides(mode=selection.mode):
                await _call_native_extract_entities_for_pair(
                    pair,
                    call_recorder,
                    config=config,
                    prompt_mode=selection.mode,
                    native_extract_entities=native_extract_entities,
                )
        except Exception as exc:
            results.append(
                ExtractEntitiesDryRunSampleResult(
                    sample_id=pair.sample_id,
                    source_us_id=pair.source_us_id,
                    feature_key=pair.feature_key,
                    domain_code=pair.domain_code,
                    section_type=pair.section_type,
                    prompt_mode=selection.mode,
                    native_extract_called=True,
                    parse_success=False,
                    entity_count=0,
                    relation_count=0,
                    allowed_entity_type_hit_rate=0.0,
                    allowed_relation_type_hit_rate=0.0,
                    invalid_entity_type_count=0,
                    invalid_relation_type_count=0,
                    snake_case_relation_count=0,
                    candidate_entity_count=0,
                    candidate_relation_count=0,
                    raw_output_preview="",
                    parse_errors=[f"NATIVE_EXTRACT_ERROR: {exc.__class__.__name__}: {exc}"],
                    risks=["Native extract_entities raised an exception."],
                )
            )
        finally:
            prompt_restored = prompt_restored and _prompt_snapshot() == before_prompts

        raw_output = call_recorder.output_at(output_index)
        if not raw_output:
            if results and results[-1].sample_id == pair.sample_id:
                continue
            raw_output = ""
        if results and results[-1].sample_id == pair.sample_id:
            continue
        parsed = parse_tuple_extraction_output(
            raw_output,
            sample_id=pair.sample_id,
            mode="dsl_aware",
            allowed_relation_types=pair.allowed_relation_types,
        )
        results.append(
            _sample_result(
                pair,
                selection.mode,
                parsed,
                raw_output=raw_output,
                native_extract_called=True,
            )
        )

    risks.extend(_report_risks(results, prompt_restored=prompt_restored))
    report = _report_from_results(
        results,
        enabled=True,
        live_llm_used=llm_callable is not None and config.run_live_llm,
        run_gleaning=config.run_gleaning,
        prompt_selector_used=config.use_prompt_selector,
        prompt_override_method="temporary_prompt_override",
        risks=risks,
        prompt_override_restored=prompt_restored,
    )
    return report


def serialize_extract_entities_dry_run_report(
    report: ExtractEntitiesDryRunReport,
) -> dict[str, Any]:
    return {
        "enabled": report.enabled,
        "skipped": report.skipped,
        "skipReason": report.skip_reason,
        "nativeExtractCalled": report.native_extract_called,
        "liveLlmUsed": report.live_llm_used,
        "sampleCount": report.sample_count,
        "baselineSampleCount": report.baseline_sample_count,
        "dslAwareSampleCount": report.dsl_aware_sample_count,
        "runGleaning": report.run_gleaning,
        "promptSelectorUsed": report.prompt_selector_used,
        "promptOverrideMethod": report.prompt_override_method,
        "storageWritten": report.storage_written,
        "graphMergeCalled": report.graph_merge_called,
        "parserModified": report.parser_modified,
        "tupleParseSuccessRate": report.tuple_parse_success_rate,
        "dslAwareParseSuccessRate": report.dsl_aware_parse_success_rate,
        "entityTypeHitRate": report.entity_type_hit_rate,
        "relationTypeHitRate": report.relation_type_hit_rate,
        "invalidEntityTypeCount": report.invalid_entity_type_count,
        "invalidRelationTypeCount": report.invalid_relation_type_count,
        "snakeCaseRelationCount": report.snake_case_relation_count,
        "candidateEntityCount": report.candidate_entity_count,
        "candidateRelationCount": report.candidate_relation_count,
        "completionDelimiterMissingCount": report.completion_delimiter_missing_count,
        "incompleteTupleCount": report.incomplete_tuple_count,
        "tupleFormatViolationCount": report.tuple_format_violation_count,
        "aggregateSummary": report.aggregate_summary,
        "recommendedNextStep": report.recommended_next_step,
        "risks": report.risks,
        "nativeUnsupported": report.native_unsupported,
        "promptOverrideRestored": report.prompt_override_restored,
        "fallbackEvaluatorCalled": report.fallback_evaluator_called,
        "sampleResults": [asdict(result) for result in report.sample_results],
    }


async def _call_native_extract_entities_for_pair(
    pair: ExtractionInputPair,
    llm_callable,
    *,
    config: ExtractEntitiesDryRunConfig,
    prompt_mode: str,
    native_extract_entities,
) -> list:
    chunks = {
        pair.sample_id: {
            "tokens": len(pair.dsl_aware_input.split()),
            "content": pair.dsl_aware_input,
            "full_doc_id": pair.source_us_id or "dry-run",
            "chunk_order_index": 0,
            "file_path": "dsl_aware_extract_entities_dry_run",
        }
    }
    global_config = {
        "llm_model_func": llm_callable,
        "entity_extract_max_gleaning": _gleaning_count(config),
        "addon_params": {
            "language": "English",
            "entity_types": _entity_types_for_pair(pair, prompt_mode),
        },
        "llm_model_max_async": 1,
        "tokenizer": _SimpleTokenizer(),
        "max_extract_input_tokens": 100_000,
    }
    return await native_extract_entities(
        chunks,
        global_config,
        pipeline_status=None,
        pipeline_status_lock=None,
        llm_response_cache=None,
        text_chunks_storage=None,
    )


def _resolve_native_extract_entities():
    try:
        from lightrag.operate import extract_entities as native_extract_entities
    except Exception as exc:  # pragma: no cover - exercised in slim envs.
        return None, f"Native extract_entities import failed: {exc.__class__.__name__}: {exc}"
    return native_extract_entities, None


def _sample_result(
    pair: ExtractionInputPair,
    prompt_mode: str,
    parsed: ExtractionRunResult,
    *,
    raw_output: str,
    native_extract_called: bool,
) -> ExtractEntitiesDryRunSampleResult:
    score = _score_parsed_result(
        parsed,
        allowed_entity_types=pair.allowed_entity_types,
        allowed_relation_types=pair.allowed_relation_types,
    )
    return ExtractEntitiesDryRunSampleResult(
        sample_id=pair.sample_id,
        source_us_id=pair.source_us_id,
        feature_key=pair.feature_key,
        domain_code=pair.domain_code,
        section_type=pair.section_type,
        prompt_mode=prompt_mode,
        native_extract_called=native_extract_called,
        parse_success=_parse_success(parsed, raw_output),
        entity_count=len(parsed.entities),
        relation_count=len(parsed.relations),
        allowed_entity_type_hit_rate=score["entity_hit_rate"],
        allowed_relation_type_hit_rate=score["relation_hit_rate"],
        invalid_entity_type_count=score["invalid_entity_type_count"],
        invalid_relation_type_count=score["invalid_relation_type_count"],
        snake_case_relation_count=score["snake_case_relation_count"],
        candidate_entity_count=score["candidate_entity_count"],
        candidate_relation_count=score["candidate_relation_count"],
        raw_output_preview=_preview(raw_output, 500),
        parse_errors=parsed.parse_errors,
        risks=_sample_risks(parsed, raw_output),
        extracted_entities=[asdict(entity) for entity in parsed.entities],
        extracted_relations=[asdict(relation) for relation in parsed.relations],
    )


def _score_parsed_result(
    result: ExtractionRunResult,
    *,
    allowed_entity_types: list[str],
    allowed_relation_types: list[str],
) -> dict[str, Any]:
    allowed_entities = {_canonical_type(value) for value in allowed_entity_types}
    allowed_relations = set(allowed_relation_types)
    entity_count = len(result.entities)
    relation_count = len(result.relations)
    entity_hits = sum(
        1 for entity in result.entities if _canonical_type(entity.entity_type) in allowed_entities
    )
    relation_hits = sum(
        1
        for relation in result.relations
        if relation.relation_type in allowed_relations
    )
    candidate_entity_count = sum(
        1
        for entity in result.entities
        if _canonical_type(entity.entity_type) == "candidateentity"
    )
    candidate_relation_count = sum(
        1
        for relation in result.relations
        if relation.relation_type == "CandidateRelation"
        or "CandidateRelation" in relation.relationship_keywords
    )
    invalid_entity_type_count = sum(
        1
        for entity in result.entities
        if _canonical_type(entity.entity_type) not in allowed_entities
        and _canonical_type(entity.entity_type) != "candidateentity"
    )
    invalid_relation_type_count = sum(
        1
        for relation in result.relations
        if relation.relation_type not in allowed_relations
        and relation.relation_type != "CandidateRelation"
    )
    snake_case_relation_count = sum(
        1
        for relation in result.relations
        if is_snake_case_relation(relation.relation_type)
        or is_snake_case_relation(relation.relationship_keywords)
    )
    return {
        "entity_hit_rate": entity_hits / entity_count if entity_count else 0.0,
        "relation_hit_rate": relation_hits / relation_count if relation_count else 0.0,
        "invalid_entity_type_count": invalid_entity_type_count,
        "invalid_relation_type_count": invalid_relation_type_count,
        "snake_case_relation_count": snake_case_relation_count,
        "candidate_entity_count": candidate_entity_count,
        "candidate_relation_count": candidate_relation_count,
    }


class _RecordingLlmCallable:
    def __init__(self, llm_callable, *, max_tokens: int | None) -> None:
        self.llm_callable = llm_callable
        self.max_tokens = max_tokens
        self.outputs: list[str] = []

    async def __call__(self, prompt: str, **kwargs) -> str:
        if self.max_tokens is not None:
            kwargs.setdefault("max_tokens", self.max_tokens)
        result = self.llm_callable(prompt, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        text = str(result)
        self.outputs.append(text)
        return text

    def output_at(self, index: int) -> str:
        if index >= len(self.outputs):
            return ""
        return self.outputs[index]


def _deterministic_native_llm(prompt: str, **_kwargs) -> str:
    delimiter = DEFAULT_TUPLE_DELIMITER
    completion = DEFAULT_COMPLETION_DELIMITER
    if "<DSL_CONTEXT>" in prompt:
        allowed_entities = _prompt_list(prompt, "allowedEntityTypes")
        allowed_relations = _prompt_list(prompt, "allowedRelationTypes")
        source_text = _prompt_source_text(prompt)
        feature_key = _prompt_scalar(prompt, "featureKey") or "FeatureCatalog"
        entity_type = _preferred_type(
            allowed_entities,
            ["FieldSpec", "RuleAtom", "TaskRule", "BackendApi", "FeatureCatalog"],
            fallback="CandidateEntity",
        )
        entity_name = _source_grounded_entity_name(source_text, entity_type, feature_key)
        relation_type = _preferred_relation_type(allowed_relations, entity_type)
        return "\n".join(
            [
                delimiter.join(
                    [
                        "entity",
                        entity_name,
                        entity_type,
                        f"{entity_name} is grounded in the source text.",
                    ]
                ),
                delimiter.join(
                    [
                        "relation",
                        feature_key,
                        entity_name,
                        relation_type,
                        f"{feature_key} is linked to {entity_name} in source evidence.",
                    ]
                ),
                completion,
            ]
        )
    return "\n".join(
        [
            delimiter.join(["entity", "Acme", "Organization", "Acme is in the text."]),
            completion,
        ]
    )


def _prompt_list(prompt: str, key: str) -> list[str]:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]', prompt, flags=re.S)
    if not match:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))


def _prompt_scalar(prompt: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]+)"', prompt)
    return match.group(1) if match else None


def _prompt_source_text(prompt: str) -> str:
    match = re.search(r"<SOURCE_TEXT>\s*(.*?)\s*</SOURCE_TEXT>", prompt, flags=re.S)
    return match.group(1) if match else prompt


def _preferred_type(
    allowed: list[str],
    preferred: list[str],
    *,
    fallback: str,
) -> str:
    for candidate in preferred:
        if candidate in allowed:
            return candidate
    for candidate in allowed:
        if candidate != fallback:
            return candidate
    return fallback


def _preferred_relation_type(allowed: list[str], entity_type: str) -> str:
    if entity_type == "FieldSpec" and "HasFieldSpec" in allowed:
        return "HasFieldSpec"
    if entity_type == "RuleAtom" and "HasRuleAtom" in allowed:
        return "HasRuleAtom"
    if entity_type == "TaskRule" and "GeneratesTask" in allowed:
        return "GeneratesTask"
    if entity_type == "BackendApi" and "CallsBackendApi" in allowed:
        return "CallsBackendApi"
    for candidate in allowed:
        if candidate != "CandidateRelation":
            return candidate
    return "CandidateRelation"


def _source_grounded_entity_name(
    source_text: str,
    entity_type: str,
    feature_key: str,
) -> str:
    if entity_type == "FieldSpec":
        table_name = _first_table_cell(source_text)
        if table_name:
            return table_name
    phrase_match = re.search(r"[A-Za-z][A-Za-z0-9 /_-]{2,48}", source_text)
    if phrase_match:
        return phrase_match.group(0).strip(" -_/")
    return feature_key.split(":")[-1] or "Source Object"


def _first_table_cell(source_text: str) -> str | None:
    ignored = {"字段名称", "---", "field name", "field"}
    for line in source_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if first.lower() in ignored or set(first) <= {"-", ":"}:
            continue
        return first
    return None


def _normalize_pairs(
    extraction_items: (
        DslAwareIngestionPayload
        | list[ExtractionInputPair]
        | list[ExtractionPayloadItem]
        | list[dict[str, Any]]
    ),
) -> list[ExtractionInputPair]:
    if isinstance(extraction_items, DslAwareIngestionPayload):
        return select_extraction_eval_samples(
            extraction_items,
            max_samples=HARD_MAX_SAMPLES,
            preferred_sections=DEFAULT_PREFERRED_SECTIONS,
            preferred_domains=DEFAULT_PREFERRED_DOMAINS,
        )
    pairs: list[ExtractionInputPair] = []
    for index, item in enumerate(extraction_items):
        if isinstance(item, ExtractionInputPair):
            pairs.append(item)
        elif isinstance(item, ExtractionPayloadItem):
            pairs.append(_pair_from_payload_item(item, index))
        else:
            pairs.append(_pair_from_dict(item, index))
    return pairs


def _cap_pairs(
    pairs: list[ExtractionInputPair],
    config: ExtractEntitiesDryRunConfig,
) -> tuple[list[ExtractionInputPair], list[str]]:
    risks: list[str] = []
    if config.max_samples > config.hard_max_samples:
        risks.append(
            f"max_samples capped from {config.max_samples} to {config.hard_max_samples}."
        )
    max_samples = min(config.max_samples, config.hard_max_samples)
    return pairs[:max_samples], risks


def _pair_from_payload_item(item: ExtractionPayloadItem, index: int) -> ExtractionInputPair:
    metadata = item.metadata
    return ExtractionInputPair(
        sample_id=item.chunk_id or f"sample-{index}",
        source_us_id=_metadata_str(metadata, "sourceUsId"),
        feature_key=_metadata_str(metadata, "featureKey"),
        domain_code=_metadata_str(metadata, "domainCode"),
        section_type=_metadata_str(metadata, "sectionType") or "unknown",
        baseline_input=_source_text_from_extraction_content(item.content),
        dsl_aware_input=item.content,
        allowed_entity_types=_metadata_list(metadata, "allowedEntityTypes"),
        allowed_relation_types=_metadata_list(metadata, "allowedRelationTypes"),
        expected_entities=[],
        expected_relations=[],
        evidence_keywords=_evidence_keywords(item.content),
    )


def _pair_from_dict(item: dict[str, Any], index: int) -> ExtractionInputPair:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    content = str(item.get("content") or "")
    return ExtractionInputPair(
        sample_id=str(item.get("chunk_id") or item.get("chunkId") or f"sample-{index}"),
        source_us_id=_metadata_str(metadata, "sourceUsId"),
        feature_key=_metadata_str(metadata, "featureKey"),
        domain_code=_metadata_str(metadata, "domainCode"),
        section_type=_metadata_str(metadata, "sectionType") or "unknown",
        baseline_input=str(item.get("baseline_input") or _source_text_from_extraction_content(content)),
        dsl_aware_input=content,
        allowed_entity_types=_metadata_list(metadata, "allowedEntityTypes"),
        allowed_relation_types=_metadata_list(metadata, "allowedRelationTypes"),
        expected_entities=[],
        expected_relations=[],
        evidence_keywords=_evidence_keywords(content),
    )


def _report_from_results(
    results: list[ExtractEntitiesDryRunSampleResult],
    *,
    enabled: bool,
    live_llm_used: bool,
    run_gleaning: bool,
    prompt_selector_used: bool,
    prompt_override_method: str,
    risks: list[str],
    prompt_override_restored: bool,
) -> ExtractEntitiesDryRunReport:
    sample_count = len(results)
    parse_success_count = sum(1 for result in results if result.parse_success)
    completion_missing = sum(
        1 for result in results if "Completion delimiter missing." in result.risks
    )
    incomplete_tuple = sum(
        1 for result in results if "Incomplete tuple record found." in result.risks
    )
    tuple_violations = sum(
        1
        for result in results
        if not result.parse_success
        or "Completion delimiter missing." in result.risks
        or "Incomplete tuple record found." in result.risks
    )
    entity_hit_rate = _avg(result.allowed_entity_type_hit_rate for result in results)
    relation_hit_rate = _avg(result.allowed_relation_type_hit_rate for result in results)
    report = ExtractEntitiesDryRunReport(
        enabled=enabled,
        skipped=False,
        skip_reason=None,
        native_extract_called=any(result.native_extract_called for result in results),
        live_llm_used=live_llm_used,
        sample_count=sample_count,
        baseline_sample_count=0,
        dsl_aware_sample_count=sample_count,
        run_gleaning=run_gleaning,
        prompt_selector_used=prompt_selector_used,
        prompt_override_method=prompt_override_method,
        storage_written=False,
        graph_merge_called=False,
        parser_modified=False,
        tuple_parse_success_rate=parse_success_count / sample_count if sample_count else 0.0,
        dsl_aware_parse_success_rate=parse_success_count / sample_count if sample_count else 0.0,
        entity_type_hit_rate=entity_hit_rate,
        relation_type_hit_rate=relation_hit_rate,
        invalid_entity_type_count=sum(result.invalid_entity_type_count for result in results),
        invalid_relation_type_count=sum(result.invalid_relation_type_count for result in results),
        snake_case_relation_count=sum(result.snake_case_relation_count for result in results),
        candidate_entity_count=sum(result.candidate_entity_count for result in results),
        candidate_relation_count=sum(result.candidate_relation_count for result in results),
        completion_delimiter_missing_count=completion_missing,
        incomplete_tuple_count=incomplete_tuple,
        tuple_format_violation_count=tuple_violations,
        sample_results=results,
        recommended_next_step="",
        risks=risks,
        prompt_override_restored=prompt_override_restored,
    )
    report.recommended_next_step = _recommended_next_step(report)
    report.aggregate_summary = {
        "sampleCount": report.sample_count,
        "tupleParseSuccessRate": report.tuple_parse_success_rate,
        "dslAwareParseSuccessRate": report.dsl_aware_parse_success_rate,
        "entityTypeHitRate": report.entity_type_hit_rate,
        "relationTypeHitRate": report.relation_type_hit_rate,
        "invalidEntityTypeCount": report.invalid_entity_type_count,
        "invalidRelationTypeCount": report.invalid_relation_type_count,
        "snakeCaseRelationCount": report.snake_case_relation_count,
        "candidateRelationCount": report.candidate_relation_count,
        "storageWritten": report.storage_written,
        "graphMergeCalled": report.graph_merge_called,
        "parserModified": report.parser_modified,
        "promptOverrideRestored": report.prompt_override_restored,
    }
    return report


def _skipped_report(
    *,
    enabled: bool,
    skip_reason: str,
    recommended_next_step: str = "ENABLE_FEATURE_FLAG_TO_RUN_NATIVE_DRY_RUN",
) -> ExtractEntitiesDryRunReport:
    return ExtractEntitiesDryRunReport(
        enabled=enabled,
        skipped=True,
        skip_reason=skip_reason,
        native_extract_called=False,
        live_llm_used=False,
        sample_count=0,
        baseline_sample_count=0,
        dsl_aware_sample_count=0,
        run_gleaning=False,
        prompt_selector_used=False,
        prompt_override_method="none",
        storage_written=False,
        graph_merge_called=False,
        parser_modified=False,
        tuple_parse_success_rate=0.0,
        dsl_aware_parse_success_rate=0.0,
        entity_type_hit_rate=0.0,
        relation_type_hit_rate=0.0,
        invalid_entity_type_count=0,
        invalid_relation_type_count=0,
        snake_case_relation_count=0,
        candidate_entity_count=0,
        candidate_relation_count=0,
        completion_delimiter_missing_count=0,
        incomplete_tuple_count=0,
        tuple_format_violation_count=0,
        recommended_next_step=recommended_next_step,
        aggregate_summary={"skipReason": skip_reason},
    )


def _unsupported_report(reason: str) -> ExtractEntitiesDryRunReport:
    report = _skipped_report(
        enabled=True,
        skip_reason=reason,
        recommended_next_step="IMPLEMENT_PROMPT_OVERRIDE_BEFORE_NATIVE_EXTRACT",
    )
    report.native_unsupported = True
    report.prompt_override_method = "unsupported"
    return report


async def _fallback_evaluator_report(
    pairs: list[ExtractionInputPair],
    *,
    reason: str,
    risks: list[str],
    llm_callable=None,
) -> ExtractEntitiesDryRunReport:
    results: list[ExtractEntitiesDryRunSampleResult] = []
    for pair in pairs:
        if llm_callable is None:
            raw_output = _deterministic_native_llm(pair.dsl_aware_input)
        else:
            raw = llm_callable(pair.dsl_aware_input)
            if asyncio.iscoroutine(raw):
                raw = await raw
            raw_output = str(raw)
        parsed = parse_tuple_extraction_output(
            raw_output,
            sample_id=pair.sample_id,
            mode="dsl_aware",
            allowed_relation_types=pair.allowed_relation_types,
        )
        selection = select_extraction_prompts(
            pair.dsl_aware_input,
            entity_types=pair.allowed_entity_types,
        )
        results.append(
            _sample_result(
                pair,
                selection.mode,
                parsed,
                raw_output=raw_output,
                native_extract_called=False,
            )
        )
    report = _report_from_results(
        results,
        enabled=True,
        live_llm_used=False,
        run_gleaning=False,
        prompt_selector_used=True,
        prompt_override_method="unsupported",
        risks=[*risks, reason],
        prompt_override_restored=True,
    )
    report.native_unsupported = True
    report.fallback_evaluator_called = True
    report.native_extract_called = False
    report.recommended_next_step = "IMPLEMENT_PROMPT_OVERRIDE_BEFORE_NATIVE_EXTRACT"
    report.aggregate_summary["nativeUnsupportedReason"] = reason
    return report


def _quality_gate_status(payload: DslAwareIngestionPayload) -> str:
    quality_gate = payload.summary.get("qualityGate")
    if isinstance(quality_gate, dict):
        status = quality_gate.get("status")
        if isinstance(status, str):
            return status
    return ""


def _templates_for_mode(mode: str) -> dict[str, Any]:
    if mode == PROMPT_MODE_DSL_AWARE:
        return {
            "system": dsl_aware_prompts.SYSTEM_PROMPT,
            "user": dsl_aware_prompts.USER_PROMPT,
            "continue": dsl_aware_prompts.CONTINUE_PROMPT,
            "examples": dsl_aware_prompts.EXAMPLES,
        }
    if mode == PROMPT_MODE_PRODUCT_DESIGN:
        return {
            "system": product_design_prompts.SYSTEM_PROMPT,
            "user": product_design_prompts.USER_PROMPT,
            "continue": product_design_prompts.CONTINUE_PROMPT,
            "examples": product_design_prompts.EXAMPLES,
        }
    return {
        "system": generic_prompts.SYSTEM_PROMPT,
        "user": generic_prompts.USER_PROMPT,
        "continue": generic_prompts.CONTINUE_PROMPT,
        "examples": generic_prompts.EXAMPLES,
    }


def _prompt_snapshot() -> dict[str, Any]:
    return {
        "DEFAULT_TUPLE_DELIMITER": PROMPTS["DEFAULT_TUPLE_DELIMITER"],
        "DEFAULT_COMPLETION_DELIMITER": PROMPTS["DEFAULT_COMPLETION_DELIMITER"],
        "entity_extraction_system_prompt": PROMPTS["entity_extraction_system_prompt"],
        "entity_extraction_user_prompt": PROMPTS["entity_extraction_user_prompt"],
        "entity_continue_extraction_user_prompt": PROMPTS[
            "entity_continue_extraction_user_prompt"
        ],
        "entity_extraction_examples": list(PROMPTS["entity_extraction_examples"]),
    }


def _gleaning_count(config: ExtractEntitiesDryRunConfig) -> int:
    if not config.run_gleaning:
        return 0
    return min(config.max_gleaning_samples, config.hard_max_gleaning_samples)


def _entity_types_for_pair(pair: ExtractionInputPair, prompt_mode: str) -> list[str]:
    if prompt_mode == PROMPT_MODE_DSL_AWARE and pair.allowed_entity_types:
        return pair.allowed_entity_types
    if prompt_mode == PROMPT_MODE_PRODUCT_DESIGN:
        return product_design_prompts.DEFAULT_ENTITY_TYPES
    if prompt_mode == PROMPT_MODE_GENERIC:
        return generic_prompts.DEFAULT_ENTITY_TYPES
    return pair.allowed_entity_types or dsl_aware_prompts.DEFAULT_ENTITY_TYPES


def _parse_success(result: ExtractionRunResult, raw_output: str) -> bool:
    return (
        DEFAULT_COMPLETION_DELIMITER in raw_output
        and not result.parse_errors
        and (bool(result.entities) or bool(result.relations))
    )


def _sample_risks(result: ExtractionRunResult, raw_output: str) -> list[str]:
    risks: list[str] = []
    if DEFAULT_COMPLETION_DELIMITER not in raw_output:
        risks.append("Completion delimiter missing.")
    if result.parse_errors:
        risks.append("Tuple parse errors found.")
    if _has_incomplete_tuple(raw_output):
        risks.append("Incomplete tuple record found.")
    return risks


def _has_incomplete_tuple(raw_output: str) -> bool:
    for line in raw_output.splitlines():
        stripped = line.strip()
        if not stripped or stripped == DEFAULT_COMPLETION_DELIMITER:
            continue
        if stripped.startswith("entity") and len(stripped.split(DEFAULT_TUPLE_DELIMITER)) != 4:
            return True
        if stripped.startswith("relation") and len(stripped.split(DEFAULT_TUPLE_DELIMITER)) != 5:
            return True
    return False


def _report_risks(
    results: list[ExtractEntitiesDryRunSampleResult],
    *,
    prompt_restored: bool,
) -> list[str]:
    risks: list[str] = []
    if not prompt_restored:
        risks.append("PROMPTS were not restored after temporary override.")
    if any(not result.parse_success for result in results):
        risks.append("At least one native extraction output failed tuple parsing.")
    if any(result.snake_case_relation_count for result in results):
        risks.append("Snake_case relationship keywords found.")
    return risks


def _recommended_next_step(report: ExtractEntitiesDryRunReport) -> str:
    if report.skipped:
        return "ENABLE_FEATURE_FLAG_TO_RUN_NATIVE_DRY_RUN"
    if report.native_unsupported:
        return "IMPLEMENT_PROMPT_OVERRIDE_BEFORE_NATIVE_EXTRACT"
    if report.tuple_format_violation_count > 0:
        return "FIX_NATIVE_TUPLE_OUTPUT_STABILITY"
    if report.dsl_aware_parse_success_rate < 0.95:
        return "FIX_NATIVE_PARSE_STABILITY"
    if report.invalid_relation_type_count or report.snake_case_relation_count:
        return "TUNE_DSL_AWARE_PROMPT_FOR_NATIVE_EXTRACT"
    return "CONSIDER_STORAGE_WRITE_DRY_RUN_DESIGN"


def _source_text_from_extraction_content(content: str) -> str:
    start = content.find("<SOURCE_TEXT>")
    end = content.find("</SOURCE_TEXT>")
    if start == -1 or end == -1 or end < start:
        return content
    return content[start + len("<SOURCE_TEXT>") : end].strip()


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _metadata_list(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _evidence_keywords(content: str) -> list[str]:
    return [keyword for keyword in EVIDENCE_KEYWORDS if keyword in content][:6]


def _canonical_type(value: str) -> str:
    return value.replace(" ", "").lower()


def _preview(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _avg(values: Iterable[float]) -> float:
    values_list = list(values)
    return sum(values_list) / len(values_list) if values_list else 0.0


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _optional_env_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


__all__ = [
    "ExtractEntitiesDryRunConfig",
    "ExtractEntitiesDryRunReport",
    "ExtractEntitiesDryRunSampleResult",
    "InMemoryKVStorage",
    "arun_extract_entities_dry_run_from_payload",
    "arun_native_extract_entities_dry_run",
    "run_extract_entities_dry_run_from_payload",
    "run_native_extract_entities_dry_run",
    "serialize_extract_entities_dry_run_report",
    "temporary_prompt_overrides",
]
