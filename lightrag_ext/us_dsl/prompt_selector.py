from __future__ import annotations

from dataclasses import dataclass, field

from lightrag.prompt import PROMPTS

from . import dsl_aware_prompts, generic_prompts, product_design_prompts


PROMPT_MODE_DSL_AWARE = "DSL_AWARE"
PROMPT_MODE_PRODUCT_DESIGN = "PRODUCT_DESIGN"
PROMPT_MODE_GENERIC = "GENERIC"

REASON_HAS_DSL_CONTEXT = "HAS_DSL_CONTEXT"
REASON_HAS_PRODUCT_DESIGN_MARKERS = "HAS_PRODUCT_DESIGN_MARKERS"
REASON_GENERIC_TEXT = "GENERIC_TEXT"
REASON_EXPLICIT_MODE = "EXPLICIT_MODE"
REASON_FALLBACK = "FALLBACK"

PRODUCT_DESIGN_MARKERS = (
    "【As】",
    "【I Want】",
    "【So That】",
    "【Given】",
    "【When】",
    "【Then】",
    "详细业务规则",
    "业务规则",
    "字段/规则表",
    "字段名称",
    "字段类型",
    "是否必填",
    "DFX / 异常处理",
    "验收标准",
    "审批",
    "待办",
    "台账",
    "接口",
    "报表",
    "迁移",
    "AuditLog",
)


@dataclass(frozen=True)
class PromptSelectorConfig:
    mode: str = "auto"
    prefer_dsl_context: bool = True
    allow_product_design_without_dsl: bool = True
    fallback_to_generic: bool = True
    tuple_delimiter: str = PROMPTS["DEFAULT_TUPLE_DELIMITER"]
    completion_delimiter: str = PROMPTS["DEFAULT_COMPLETION_DELIMITER"]


@dataclass(frozen=True)
class PromptSelectionResult:
    mode: str
    reason: str
    system_prompt: str
    user_prompt: str
    continue_prompt: str
    tuple_delimiter: str
    completion_delimiter: str
    parser_mode: str = "tuple_delimited"
    output_format: str = "tuple_delimited"
    risks: list[str] = field(default_factory=list)


def select_extraction_prompts(
    input_text: str,
    *,
    config: PromptSelectorConfig | None = None,
    entity_types: list[str] | None = None,
    language: str = "English",
) -> PromptSelectionResult:
    return _select(
        input_text,
        config=config or PromptSelectorConfig(),
        entity_types=entity_types,
        language=language,
    )


def select_continue_prompt(
    input_text: str,
    *,
    previous_output: str | None = None,
    config: PromptSelectorConfig | None = None,
    entity_types: list[str] | None = None,
    language: str = "English",
) -> PromptSelectionResult:
    # previous_output is accepted for future hook parity; prompt selection is based
    # on the original extraction input.
    _ = previous_output
    return _select(
        input_text,
        config=config or PromptSelectorConfig(),
        entity_types=entity_types,
        language=language,
    )


def _select(
    input_text: str,
    *,
    config: PromptSelectorConfig,
    entity_types: list[str] | None,
    language: str,
) -> PromptSelectionResult:
    explicit_mode = _explicit_mode(config.mode)
    risks: list[str] = []
    if explicit_mode is not None:
        mode = explicit_mode
        reason = REASON_EXPLICIT_MODE
        risks.append(f"Explicit prompt mode override: {mode}.")
    elif config.prefer_dsl_context and has_dsl_context(input_text):
        mode = PROMPT_MODE_DSL_AWARE
        reason = REASON_HAS_DSL_CONTEXT
    elif config.allow_product_design_without_dsl and has_product_design_markers(
        input_text
    ):
        mode = PROMPT_MODE_PRODUCT_DESIGN
        reason = REASON_HAS_PRODUCT_DESIGN_MARKERS
    elif config.fallback_to_generic:
        mode = PROMPT_MODE_GENERIC
        reason = REASON_GENERIC_TEXT
    else:
        mode = PROMPT_MODE_GENERIC
        reason = REASON_FALLBACK
        risks.append("Prompt selector fell back to generic mode.")

    templates, default_types = _templates_for_mode(mode)
    active_entity_types = entity_types or default_types
    context = {
        "tuple_delimiter": config.tuple_delimiter,
        "completion_delimiter": config.completion_delimiter,
        "entity_types": ",".join(active_entity_types),
        "language": language,
        "examples": "\n".join(templates["examples"]).format(
            tuple_delimiter=config.tuple_delimiter,
            completion_delimiter=config.completion_delimiter,
            entity_types=",".join(active_entity_types),
            language=language,
        ),
        "input_text": input_text,
    }
    return PromptSelectionResult(
        mode=mode,
        reason=reason,
        system_prompt=templates["system"].format(**context),
        user_prompt=templates["user"].format(**context),
        continue_prompt=templates["continue"].format(**context),
        tuple_delimiter=config.tuple_delimiter,
        completion_delimiter=config.completion_delimiter,
        risks=risks,
    )


def has_dsl_context(input_text: str) -> bool:
    return (
        "<DSL_CONTEXT>" in input_text
        and "</DSL_CONTEXT>" in input_text
        and "<SOURCE_TEXT>" in input_text
        and "</SOURCE_TEXT>" in input_text
        and (
            "allowedEntityTypes" in input_text
            or "allowedRelationTypes" in input_text
        )
    )


def has_product_design_markers(input_text: str) -> bool:
    return any(marker in input_text for marker in PRODUCT_DESIGN_MARKERS)


def _explicit_mode(mode: str) -> str | None:
    normalized = mode.lower()
    if normalized in {"auto", ""}:
        return None
    if normalized in {"dsl_aware", "dsl-aware", "dsl"}:
        return PROMPT_MODE_DSL_AWARE
    if normalized in {"product_design", "product-design", "product"}:
        return PROMPT_MODE_PRODUCT_DESIGN
    if normalized == "generic":
        return PROMPT_MODE_GENERIC
    return None


def _templates_for_mode(mode: str) -> tuple[dict[str, object], list[str]]:
    if mode == PROMPT_MODE_DSL_AWARE:
        return (
            {
                "system": dsl_aware_prompts.SYSTEM_PROMPT,
                "user": dsl_aware_prompts.USER_PROMPT,
                "continue": dsl_aware_prompts.CONTINUE_PROMPT,
                "examples": dsl_aware_prompts.EXAMPLES,
            },
            dsl_aware_prompts.DEFAULT_ENTITY_TYPES,
        )
    if mode == PROMPT_MODE_PRODUCT_DESIGN:
        return (
            {
                "system": product_design_prompts.SYSTEM_PROMPT,
                "user": product_design_prompts.USER_PROMPT,
                "continue": product_design_prompts.CONTINUE_PROMPT,
                "examples": product_design_prompts.EXAMPLES,
            },
            product_design_prompts.DEFAULT_ENTITY_TYPES,
        )
    return (
        {
            "system": generic_prompts.SYSTEM_PROMPT,
            "user": generic_prompts.USER_PROMPT,
            "continue": generic_prompts.CONTINUE_PROMPT,
            "examples": generic_prompts.EXAMPLES,
        },
        generic_prompts.DEFAULT_ENTITY_TYPES,
    )
