from __future__ import annotations

from dataclasses import dataclass
from typing import Any

FEATURE_FLAG_NAMES = [
    "DSL_AWARE_RUNTIME_ENABLED",
    "DSL_ROUTER_MODE",
    "PFSS_WRITE_ENABLED",
    "GENERIC_GRAPH_ENABLED",
    "ISSUE_INDEX_ENABLED",
    "VERSION_AWARE_RETRIEVAL_ENABLED",
    "TRUSTED_HYBRID_RETRIEVAL_ENABLED",
    "FUNCTIONAL_QA_ENABLED",
    "IMPACT_ANALYSIS_ENABLED",
    "QUALITY_GATE_ENABLED",
    "REAL_MODEL_CALLS_ENABLED",
    "REMOTE_STORAGE_ENABLED",
    "LIVE_UPLOAD_INTEGRATION_ENABLED",
    "LIVE_QUERY_INTEGRATION_ENABLED",
]

SAFE_FLAG_DEFAULTS: dict[str, bool | str] = {
    "DSL_AWARE_RUNTIME_ENABLED": False,
    "DSL_ROUTER_MODE": "shadow",
    "PFSS_WRITE_ENABLED": False,
    "GENERIC_GRAPH_ENABLED": False,
    "ISSUE_INDEX_ENABLED": False,
    "VERSION_AWARE_RETRIEVAL_ENABLED": True,
    "TRUSTED_HYBRID_RETRIEVAL_ENABLED": True,
    "FUNCTIONAL_QA_ENABLED": True,
    "IMPACT_ANALYSIS_ENABLED": True,
    "QUALITY_GATE_ENABLED": True,
    "REAL_MODEL_CALLS_ENABLED": False,
    "REMOTE_STORAGE_ENABLED": False,
    "LIVE_UPLOAD_INTEGRATION_ENABLED": False,
    "LIVE_QUERY_INTEGRATION_ENABLED": False,
}

LIVE_FLAGS = {
    "LIVE_UPLOAD_INTEGRATION_ENABLED",
    "LIVE_QUERY_INTEGRATION_ENABLED",
    "REMOTE_STORAGE_ENABLED",
    "REAL_MODEL_CALLS_ENABLED",
}


@dataclass(frozen=True)
class FeatureFlagResolution:
    flags: dict[str, bool | str]
    sources: dict[str, str]
    violations: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "flags": dict(self.flags),
            "sources": dict(self.sources),
            "violations": list(self.violations),
        }


def coerce_bool(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return value


def resolve_feature_flags(
    *,
    file_values: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    cli_overrides: dict[str, Any] | None = None,
    deployment_mode: str = "PRODUCTION_DISABLED",
) -> FeatureFlagResolution:
    flags: dict[str, bool | str] = dict(SAFE_FLAG_DEFAULTS)
    sources = {name: "default" for name in FEATURE_FLAG_NAMES}
    for source_name, values in [
        ("config_file", file_values or {}),
        ("env", env or {}),
        ("cli", cli_overrides or {}),
    ]:
        for name in FEATURE_FLAG_NAMES:
            if name in values:
                flags[name] = coerce_bool(values[name])
                sources[name] = source_name
    return FeatureFlagResolution(flags, sources, validate_feature_flags(flags, deployment_mode=deployment_mode))


def validate_feature_flags(flags: dict[str, Any], *, deployment_mode: str = "PRODUCTION_DISABLED") -> list[str]:
    violations: list[str] = []
    if flags.get("PFSS_WRITE_ENABLED") and not flags.get("DSL_AWARE_RUNTIME_ENABLED"):
        violations.append("PFSS_WRITE_REQUIRES_DSL_AWARE_RUNTIME")
    if flags.get("GENERIC_GRAPH_ENABLED") and flags.get("PFSS_WRITE_ENABLED"):
        violations.append("GENERIC_GRAPH_AND_PFSS_BOTH_ENABLED_REQUIRES_EXPLICIT_GRAPH_SPACE_PLAN")
    if flags.get("LIVE_UPLOAD_INTEGRATION_ENABLED"):
        violations.append("LIVE_UPLOAD_INTEGRATION_BLOCKED_IN_28B")
    if flags.get("LIVE_QUERY_INTEGRATION_ENABLED"):
        violations.append("LIVE_QUERY_INTEGRATION_BLOCKED_IN_28B")
    if deployment_mode == "PRODUCTION_DISABLED" and any(bool(flags.get(item)) for item in LIVE_FLAGS):
        violations.append("LIVE_OR_REMOTE_FLAG_ENABLED_WHILE_PRODUCTION_DISABLED")
    if flags.get("DSL_ROUTER_MODE") not in {"raw", "dsl", "auto", "shadow"}:
        violations.append("UNSUPPORTED_DSL_ROUTER_MODE")
    return violations


def safe_defaults_report() -> dict[str, object]:
    return {
        "flags": dict(SAFE_FLAG_DEFAULTS),
        "live_flags_disabled_by_default": all(not SAFE_FLAG_DEFAULTS[name] for name in LIVE_FLAGS),
        "production_disabled_by_default": True,
    }
