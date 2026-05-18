from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dsl_types import DslCompiledResult, DslValidationError, OntologyConfig
from .dsl_validator import validate_dsl_compiled
from .ontology_loader import load_ontology


def load_dsl_compiled(
    path: str | Path,
    ontology: OntologyConfig | None = None,
    validate: bool = True,
) -> DslCompiledResult:
    dsl_path = Path(path)
    try:
        with dsl_path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{dsl_path}: invalid JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError(f"{dsl_path}: dsl-compiled.json must contain a JSON object")

    if ontology is None:
        ontology = load_ontology()

    issues = []
    if validate:
        validation = validate_dsl_compiled(raw, ontology)
        issues = validation.issues
        if validation.errors:
            raise DslValidationError(dsl_path, validation.issues)

    return DslCompiledResult(
        raw=raw,
        dsl_version=str(raw.get("dslVersion", "")),
        active_domains=_extract_active_domains(raw),
        feature_catalog_index=_extract_list(raw, "featureCatalogIndex"),
        source_vectorization_plan=_extract_list(raw, "sourceVectorizationPlan"),
        gleaning_input_blocks=_extract_list(raw, "gleaningInputBlocks"),
        issues=issues,
    )


def _extract_list(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = raw.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _extract_active_domains(raw: dict[str, Any]) -> list[str]:
    run_summary = raw.get("runSummary")
    if not isinstance(run_summary, dict):
        return []

    active_domains = run_summary.get("activeDomains")
    if not isinstance(active_domains, list):
        return []

    result = []
    for item in active_domains:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and isinstance(item.get("domainCode"), str):
            result.append(item["domainCode"])
    return result

