from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from .runtime_config_loader import find_placeholders
from .runtime_config_types import RuntimeConfig, to_plain_dict
from .runtime_feature_flags import validate_feature_flags

READY_STATUS = "READY"
NOT_READY_CONFIG = "NOT_READY_CONFIG"
NOT_READY_MODEL = "NOT_READY_MODEL"
NOT_READY_STORAGE = "NOT_READY_STORAGE"
NOT_READY_SCHEMA = "NOT_READY_SCHEMA"
NOT_READY_NAMESPACE = "NOT_READY_NAMESPACE"
NOT_READY_POLICY = "NOT_READY_POLICY"

SUPPORTED_LOCAL_STORAGE = {"LOCAL_JSON", "LOCAL_SQLITE", "LOCAL_MEMORY", "LOCAL_FILES"}
FUTURE_REMOTE_STORAGE = {"POSTGRES", "NEO4J", "MILVUS", "QDRANT", "REDIS", "MONGO", "OPENSEARCH"}


@dataclass(frozen=True)
class HealthReport:
    status: str
    process_alive: bool
    external_services_checked: bool = False
    production_disabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    ready: bool
    checks: dict[str, bool]
    reason_codes: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


def health(config: RuntimeConfig | None = None) -> HealthReport:
    return HealthReport(
        status="HEALTHY",
        process_alive=True,
        external_services_checked=False,
        production_disabled=(config.deployment_mode == "PRODUCTION_DISABLED" if config else True),
    )


def evaluate_readiness(config: RuntimeConfig) -> ReadinessReport:
    placeholders = find_placeholders(config.to_dict())
    flag_violations = validate_feature_flags(config.feature_flags, deployment_mode=config.deployment_mode)
    dimension_ok = _dimension_ok(config)
    namespace_safe = _namespace_safe(config.namespace, config.working_dir)
    sidecar_ok = config.sidecar_schema_version == config.expected_sidecar_schema_version
    ontology_ok = config.ontology_version == config.expected_ontology_version
    term_ok = config.term_registry_version == config.expected_term_registry_version
    version_ok = config.version_policy_version == config.expected_version_policy_version
    fusion_ok = config.fusion_policy_version == config.expected_fusion_policy_version
    quality_ok = config.quality_gate_version == config.expected_quality_gate_version
    storage_ok = _storage_ok(config)
    checks = {
        "health_ok": True,
        "config_valid": not placeholders,
        "required_flags_enabled": not flag_violations,
        "embedding_dimension_consistent": dimension_ok,
        "model_credentials_configured": not bool(config.feature_flags.get("REAL_MODEL_CALLS_ENABLED")),
        "storage_capability_validated": storage_ok,
        "namespace_safe": namespace_safe,
        "sidecar_schema_compatible": sidecar_ok,
        "ontology_version_compatible": ontology_ok,
        "term_registry_valid": term_ok,
        "version_policy_valid": version_ok,
        "fusion_policy_valid": fusion_ok,
        "quality_gate_loaded": quality_ok,
        "no_placeholder_config": not placeholders,
    }
    reason_codes: list[str] = []
    status = READY_STATUS
    if placeholders:
        status = NOT_READY_CONFIG
        reason_codes.append("UNREPLACED_PLACEHOLDER_CONFIG")
    elif not dimension_ok:
        status = NOT_READY_MODEL
        reason_codes.append("EMBEDDING_DIMENSION_MISMATCH")
    elif not storage_ok:
        status = NOT_READY_STORAGE
        reason_codes.append("STORAGE_BACKEND_NOT_VALIDATED")
    elif not sidecar_ok:
        status = NOT_READY_SCHEMA
        reason_codes.append("SIDECAR_SCHEMA_MISMATCH")
    elif not namespace_safe:
        status = NOT_READY_NAMESPACE
        reason_codes.append("UNSAFE_NAMESPACE_OR_WORKING_DIR")
    elif flag_violations or not all([ontology_ok, term_ok, version_ok, fusion_ok, quality_ok]):
        status = NOT_READY_POLICY
        reason_codes.extend(flag_violations or ["POLICY_VERSION_MISMATCH"])
    return ReadinessReport(
        status=status,
        ready=status == READY_STATUS,
        checks=checks,
        reason_codes=reason_codes,
        details={"placeholders": placeholders, "flag_violations": flag_violations},
    )


def _dimension_ok(config: RuntimeConfig) -> bool:
    if config.embedding_dimension is None or config.expected_embedding_dimension is None:
        return True
    return int(config.embedding_dimension) == int(config.expected_embedding_dimension)


def _storage_ok(config: RuntimeConfig) -> bool:
    backend = str(config.storage_backend)
    if backend in SUPPORTED_LOCAL_STORAGE:
        return True
    if backend in FUTURE_REMOTE_STORAGE:
        return bool(config.feature_flags.get("REMOTE_STORAGE_ENABLED")) and config.deployment_mode != "PRODUCTION_DISABLED"
    return False


def _namespace_safe(namespace: str, working_dir: str) -> bool:
    lowered = f"{namespace} {working_dir}".lower()
    if any(item in lowered for item in ["prod", "production", "formal", "live"]):
        return False
    path = PurePosixPath(working_dir)
    return not str(path).startswith(("/var", "/opt", "/data/prod", "/prod"))
