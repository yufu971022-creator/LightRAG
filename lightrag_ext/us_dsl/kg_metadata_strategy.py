from __future__ import annotations

from dataclasses import dataclass, field


STRATEGY_NATIVE_PASS_THROUGH = "NATIVE_PASS_THROUGH"
STRATEGY_SIDECAR_ONLY = "SIDECAR_ONLY"
STRATEGY_SIDECAR_PLUS_MINIMAL_NATIVE = "SIDECAR_PLUS_MINIMAL_NATIVE"
STRATEGY_UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class KgMetadataStrategy:
    strategy_name: str
    native_metadata_supported: bool
    sidecar_required: bool
    core_modification_required: bool
    selected: bool
    reason: str
    risks: list[str] = field(default_factory=list)


def determine_metadata_strategy(
    *,
    native_custom_kg_supports_metadata: bool,
    allow_core_modification: bool = False,
) -> KgMetadataStrategy:
    if native_custom_kg_supports_metadata:
        return KgMetadataStrategy(
            strategy_name=STRATEGY_SIDECAR_PLUS_MINIMAL_NATIVE,
            native_metadata_supported=True,
            sidecar_required=True,
            core_modification_required=False,
            selected=True,
            reason=(
                "Native metadata appears supported, but sidecar remains required "
                "to keep backend behavior consistent."
            ),
            risks=[
                "Backend-specific metadata behavior may differ; use sidecar as source of truth."
            ],
        )

    risks = ["native metadata pass-through requires core modification."]
    if allow_core_modification:
        risks.append("Core modification was allowed by caller, but Block 18 forbids it.")

    return KgMetadataStrategy(
        strategy_name=STRATEGY_SIDECAR_ONLY,
        native_metadata_supported=False,
        sidecar_required=True,
        core_modification_required=True,
        selected=True,
        reason=(
            "LightRAG custom_kg copies only fixed fields into graph/vector payloads; "
            "metadata must be preserved in sidecar."
        ),
        risks=risks,
    )


__all__ = [
    "KgMetadataStrategy",
    "STRATEGY_NATIVE_PASS_THROUGH",
    "STRATEGY_SIDECAR_ONLY",
    "STRATEGY_SIDECAR_PLUS_MINIMAL_NATIVE",
    "STRATEGY_UNSUPPORTED",
    "determine_metadata_strategy",
]
