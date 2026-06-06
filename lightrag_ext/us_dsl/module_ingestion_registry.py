from __future__ import annotations

from dataclasses import dataclass

from .kg_payload_types import DslKgPayload
from .lc_mini_graph_smoke import LcMiniGraphSmokeConfig, build_lc_mini_build_result


@dataclass(frozen=True)
class ModuleIngestionBuildResult:
    payload: DslKgPayload
    source: str
    source_us_count: int
    source_text_unit_count: int
    module_name: str | None


def build_module_ingestion_payload(
    *,
    module_name: str | None,
    source_path: str | None = None,
    max_chunks: int = 2000,
    max_entities: int = 5000,
    max_relationships: int = 5000,
) -> ModuleIngestionBuildResult:
    module_key = (module_name or "LCAB").upper()
    if module_key == "LCAB":
        result = build_lc_mini_build_result(
            LcMiniGraphSmokeConfig(
                lc_file_path=source_path,
                max_chunks=max_chunks,
                max_entities=max_entities,
                max_relationships=max_relationships,
            )
        )
        return ModuleIngestionBuildResult(
            payload=result.payload,
            source=result.source_path,
            source_us_count=result.source_us_count,
            source_text_unit_count=result.source_text_unit_count,
            module_name=module_key,
        )
    raise ValueError(f"Unsupported module ingestion registry key: {module_key}")


__all__ = [
    "ModuleIngestionBuildResult",
    "build_module_ingestion_payload",
]
