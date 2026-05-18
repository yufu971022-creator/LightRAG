from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .payload_types import DslAwareIngestionPayload, ExtractionPayloadItem
from .prompt_selector import (
    PromptSelectorConfig,
    select_extraction_prompts,
)


@dataclass(frozen=True)
class ExtractionHookDryRunItem:
    chunk_id: str
    source_us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str | None
    input_type: str
    selected_prompt_mode: str
    selection_reason: str
    parser_mode: str
    output_format: str
    will_call_extract_entities: bool
    will_write_storage: bool
    prompt_preview: str
    input_preview: str
    risks: list[str] = field(default_factory=list)


@dataclass
class ExtractionHookDryRunPlan:
    dry_run: bool
    write_storage: bool
    call_extract_entities: bool
    modify_parser: bool
    modify_graph_merge: bool
    item_count: int
    mode_distribution: dict[str, int]
    reason_distribution: dict[str, int]
    risks: list[str]
    items: list[ExtractionHookDryRunItem]


def build_extraction_hook_dry_run_plan(
    extraction_payload_items: (
        DslAwareIngestionPayload
        | list[ExtractionPayloadItem]
        | list[dict[str, Any]]
    ),
    *,
    selector_config: PromptSelectorConfig | None = None,
) -> ExtractionHookDryRunPlan:
    items = _normalize_items(extraction_payload_items)
    dry_run_items: list[ExtractionHookDryRunItem] = []
    risks: list[str] = []

    for item in items:
        selection = select_extraction_prompts(
            item.content,
            config=selector_config,
        )
        metadata = item.metadata
        dry_run_item = ExtractionHookDryRunItem(
            chunk_id=item.chunk_id,
            source_us_id=_metadata_str(metadata, "sourceUsId"),
            feature_key=_metadata_str(metadata, "featureKey"),
            domain_code=_metadata_str(metadata, "domainCode"),
            section_type=_metadata_str(metadata, "sectionType"),
            input_type=selection.mode.lower(),
            selected_prompt_mode=selection.mode,
            selection_reason=selection.reason,
            parser_mode=selection.parser_mode,
            output_format=selection.output_format,
            will_call_extract_entities=False,
            will_write_storage=False,
            prompt_preview=_preview(selection.system_prompt),
            input_preview=_preview(item.content),
            risks=selection.risks,
        )
        dry_run_items.append(dry_run_item)
        risks.extend(selection.risks)

    return ExtractionHookDryRunPlan(
        dry_run=True,
        write_storage=False,
        call_extract_entities=False,
        modify_parser=False,
        modify_graph_merge=False,
        item_count=len(dry_run_items),
        mode_distribution=_distribution(
            item.selected_prompt_mode for item in dry_run_items
        ),
        reason_distribution=_distribution(
            item.selection_reason for item in dry_run_items
        ),
        risks=risks,
        items=dry_run_items,
    )


def serialize_extraction_hook_dry_run_plan(
    plan: ExtractionHookDryRunPlan,
) -> dict[str, Any]:
    return {
        "dryRun": plan.dry_run,
        "writeStorage": plan.write_storage,
        "callExtractEntities": plan.call_extract_entities,
        "modifyParser": plan.modify_parser,
        "modifyGraphMerge": plan.modify_graph_merge,
        "itemCount": plan.item_count,
        "modeDistribution": plan.mode_distribution,
        "reasonDistribution": plan.reason_distribution,
        "risks": plan.risks,
        "items": [asdict(item) for item in plan.items],
    }


def _normalize_items(
    value: DslAwareIngestionPayload | list[ExtractionPayloadItem] | list[dict[str, Any]],
) -> list[ExtractionPayloadItem]:
    if isinstance(value, DslAwareIngestionPayload):
        return value.extraction_payload
    result: list[ExtractionPayloadItem] = []
    for item in value:
        if isinstance(item, ExtractionPayloadItem):
            result.append(item)
            continue
        result.append(
            ExtractionPayloadItem(
                chunk_id=str(item.get("chunk_id") or item.get("chunkId") or ""),
                content=str(item.get("content") or ""),
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            )
        )
    return result


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _preview(value: str, limit: int = 500) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def _distribution(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def _json_dumpsable(plan: ExtractionHookDryRunPlan) -> str:
    return json.dumps(serialize_extraction_hook_dry_run_plan(plan), ensure_ascii=False)
