from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

DeploymentMode = Literal[
    "LOCAL_DRY_RUN",
    "LOCAL_ISOLATED",
    "INTRANET_STAGING",
    "INTRANET_CANDIDATE",
    "PRODUCTION_DISABLED",
]


@dataclass(frozen=True)
class RuntimeConfig:
    deployment_mode: DeploymentMode = "PRODUCTION_DISABLED"
    namespace: str = "local_dry_run"
    working_dir: str = "workspaces/runtime_dry_run"
    module_manifest_path: str = "<<MODULE_MANIFEST_PATH>>"
    embedding_model: str = "<<EMBEDDING_MODEL>>"
    embedding_dimension: int | None = None
    expected_embedding_dimension: int | None = None
    llm_model: str = "<<LLM_MODEL>>"
    storage_backend: str = "<<STORAGE_BACKEND>>"
    sidecar_schema_version: str = "sidecar.v1"
    expected_sidecar_schema_version: str = "sidecar.v1"
    ontology_version: str = "ontology.v1"
    expected_ontology_version: str = "ontology.v1"
    term_registry_version: str = "term-registry.v1"
    expected_term_registry_version: str = "term-registry.v1"
    version_policy_version: str = "version-policy.v1"
    expected_version_policy_version: str = "version-policy.v1"
    fusion_policy_version: str = "fusion-policy.v1"
    expected_fusion_policy_version: str = "fusion-policy.v1"
    quality_gate_version: str = "quality-gate.v1"
    expected_quality_gate_version: str = "quality-gate.v1"
    feature_flags: dict[str, bool | str] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)
    storage: dict[str, Any] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    observability: dict[str, Any] = field(default_factory=dict)
    config_sources: dict[str, str] = field(default_factory=dict)
    flag_sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


@dataclass(frozen=True)
class RuntimeConfigReport:
    config: dict[str, Any]
    sources: dict[str, str]
    placeholders: list[str]
    secrets: dict[str, dict[str, object]]
    precedence: list[str] = field(default_factory=lambda: ["cli", "env", "config_file", "default"])

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


def to_plain_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, tuple):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain_dict(item) for key, item in value.items()}
    return value
