from __future__ import annotations

import json
from typing import Any


MAX_KNOWN_OBJECTS = 20
MAX_KNOWN_OBJECTS_SERIALIZED_CHARS = 3000
KNOWN_OBJECT_KEYS = (
    "objectType",
    "entityType",
    "entityName",
    "relationType",
    "featureKey",
    "domainCode",
)


def build_prompt_context(
    dsl_context: dict[str, Any],
    source_text: str,
    *,
    max_known_objects: int = MAX_KNOWN_OBJECTS,
    max_known_objects_serialized_chars: int = MAX_KNOWN_OBJECTS_SERIALIZED_CHARS,
) -> str:
    known_objects, known_objects_truncated = _compact_known_objects(
        dsl_context.get("knownObjects"),
        max_known_objects=max_known_objects,
        max_serialized_chars=max_known_objects_serialized_chars,
    )

    lines = [
        "<DSL_CONTEXT>",
        f"domainCode: {_scalar(dsl_context.get('domainCode'))}",
        f"featureKey: {_scalar(dsl_context.get('featureKey'))}",
        f"sectionType: {_scalar(dsl_context.get('sectionType'))}",
        f"sourceUsId: {_scalar(dsl_context.get('sourceUsId'))}",
        f"sourceTextUnitId: {_scalar(dsl_context.get('sourceTextUnitId'))}",
        f"allowedEntityTypes: {_json_compact(dsl_context.get('allowedEntityTypes', []))}",
        f"allowedRelationTypes: {_json_compact(dsl_context.get('allowedRelationTypes', []))}",
        f"knownObjects: {_json_compact(known_objects or [])}",
        f"knownObjectsTruncated: {_json_compact(known_objects_truncated)}",
        f"instruction: {_scalar(dsl_context.get('instruction'))}",
        "</DSL_CONTEXT>",
        "",
        "<SOURCE_TEXT>",
        source_text,
        "</SOURCE_TEXT>",
    ]
    return "\n".join(lines)


def _compact_known_objects(
    value: Any,
    *,
    max_known_objects: int,
    max_serialized_chars: int,
) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(value, list):
        return [], False

    compacted: list[dict[str, Any]] = []
    truncated = len(value) > max_known_objects
    for item in value:
        if not isinstance(item, dict):
            continue
        compacted.append(
            {
                key: item[key]
                for key in KNOWN_OBJECT_KEYS
                if item.get(key) is not None
            }
        )
        if len(compacted) >= max_known_objects:
            break

    while (
        compacted
        and len(_json_compact(compacted)) > max_serialized_chars
    ):
        compacted.pop()
        truncated = True

    return compacted, truncated


def _json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
