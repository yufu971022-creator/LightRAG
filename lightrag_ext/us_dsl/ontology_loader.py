from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dsl_types import OntologyConfig


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent / "config"


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def _load_type_sets(path: Path) -> dict[str, set[str]]:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected JSON object")

    result: dict[str, set[str]] = {}
    for domain_code, values in data.items():
        if not isinstance(domain_code, str) or not domain_code:
            raise ValueError(f"{path}: domain keys must be non-empty strings")
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise ValueError(f"{path}: {domain_code} must be a list of strings")
        result[domain_code] = set(values)
    return result


def load_ontology(config_dir: str | Path = DEFAULT_CONFIG_DIR) -> OntologyConfig:
    config_path = Path(config_dir)
    domains_path = config_path / "domains.json"
    entity_types_path = config_path / "entity-types.json"
    relation_types_path = config_path / "relation-types.json"

    domains_data = _load_json(domains_path)
    if not isinstance(domains_data, list):
        raise ValueError(f"{domains_path}: expected JSON array")

    domains: set[str] = set()
    domain_names: dict[str, str] = {}
    for index, item in enumerate(domains_data):
        if not isinstance(item, dict):
            raise ValueError(f"{domains_path}[{index}]: expected JSON object")
        domain_code = item.get("domainCode")
        if not isinstance(domain_code, str) or not domain_code:
            raise ValueError(f"{domains_path}[{index}].domainCode: required string")
        domains.add(domain_code)
        domain_name = item.get("domainNameZh")
        if isinstance(domain_name, str):
            domain_names[domain_code] = domain_name

    entity_types = _load_type_sets(entity_types_path)
    relation_types = _load_type_sets(relation_types_path)
    return OntologyConfig(
        domains=domains,
        entity_types=entity_types,
        relation_types=relation_types,
        domain_names=domain_names,
    )

