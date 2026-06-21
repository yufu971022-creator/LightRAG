from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .runtime_config_types import RuntimeConfig, RuntimeConfigReport, to_plain_dict
from .runtime_feature_flags import SAFE_FLAG_DEFAULTS, resolve_feature_flags

_PLACEHOLDER_RE = re.compile(r"<<[A-Z0-9_]+>>")
_SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|authorization|password|credential)", re.IGNORECASE)
_FIELD_ENV = {
    "deployment_mode": "DSL_RUNTIME_DEPLOYMENT_MODE",
    "namespace": "DSL_RUNTIME_NAMESPACE",
    "working_dir": "DSL_RUNTIME_WORKING_DIR",
    "module_manifest_path": "DSL_RUNTIME_MODULE_MANIFEST_PATH",
    "embedding_model": "EMBEDDING_MODEL",
    "embedding_dimension": "EMBEDDING_DIM",
    "expected_embedding_dimension": "EXPECTED_EMBEDDING_DIM",
    "llm_model": "LLM_MODEL",
    "storage_backend": "DSL_RUNTIME_STORAGE_BACKEND",
}


def safe_default_config() -> RuntimeConfig:
    return RuntimeConfig(feature_flags=dict(SAFE_FLAG_DEFAULTS))


def load_runtime_config(
    config_path: str | Path | None = None,
    *,
    env: dict[str, str] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> RuntimeConfig:
    source_env = env if env is not None else os.environ
    data = safe_default_config().to_dict()
    sources = {key: "default" for key in data if key not in {"config_sources", "flag_sources"}}
    file_values: dict[str, Any] = {}
    if config_path:
        file_values = _load_config_file(Path(config_path))
        _merge(data, file_values)
        for key in file_values:
            sources[key] = "config_file"
    for field_name, env_name in _FIELD_ENV.items():
        if env_name in source_env:
            data[field_name] = _coerce_scalar(source_env[env_name])
            sources[field_name] = "env"
    flag_file_values = _extract_flags(file_values)
    flag_env_values = {name: source_env[name] for name in SAFE_FLAG_DEFAULTS if name in source_env}
    flag_cli_values = _extract_flags(cli_overrides or {})
    flag_resolution = resolve_feature_flags(
        file_values=flag_file_values,
        env=flag_env_values,
        cli_overrides=flag_cli_values,
        deployment_mode=str(data.get("deployment_mode", "PRODUCTION_DISABLED")),
    )
    data["feature_flags"] = flag_resolution.flags
    if cli_overrides:
        _merge(data, {key: value for key, value in cli_overrides.items() if key != "feature_flags"})
        for key in cli_overrides:
            if key != "feature_flags":
                sources[key] = "cli"
    data["config_sources"] = sources
    data["flag_sources"] = flag_resolution.sources
    return RuntimeConfig(**{key: data[key] for key in RuntimeConfig.__dataclass_fields__ if key in data})


def build_config_report(config: RuntimeConfig) -> RuntimeConfigReport:
    plain = config.to_dict()
    secrets: dict[str, dict[str, object]] = {}
    sanitized = _sanitize_secrets(plain, secrets)
    return RuntimeConfigReport(
        config=sanitized,
        sources=dict(config.config_sources),
        placeholders=find_placeholders(plain),
        secrets=secrets,
    )


def find_placeholders(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, str):
            found.update(_PLACEHOLDER_RE.findall(item))
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)


def has_unreplaced_placeholders(value: Any) -> bool:
    return bool(find_placeholders(value))


def _load_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return _parse_simple_yaml(text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            if value.strip() == "":
                current = {}
                data[key] = current
            else:
                data[key] = _coerce_scalar(value.strip())
                current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = _coerce_scalar(value.strip())
    return data


def _merge(base: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def _extract_flags(values: dict[str, Any]) -> dict[str, Any]:
    result = dict(values.get("feature_flags", {})) if isinstance(values.get("feature_flags"), dict) else {}
    for name in SAFE_FLAG_DEFAULTS:
        if name in values:
            result[name] = values[name]
    return result


def _coerce_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip().strip('"').strip("'")
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    try:
        return int(stripped)
    except ValueError:
        return stripped


def _sanitize_secrets(value: Any, secrets: dict[str, dict[str, object]], path: str = "") -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if _SECRET_KEY_RE.search(str(key)):
                text = "" if child is None else str(child)
                secrets[child_path] = {
                    "configured": bool(text),
                    "masked_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else "",
                }
                sanitized[str(key)] = {"configured": bool(text), "masked": True}
            else:
                sanitized[str(key)] = _sanitize_secrets(child, secrets, child_path)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_secrets(item, secrets, path) for item in value]
    return to_plain_dict(value)
