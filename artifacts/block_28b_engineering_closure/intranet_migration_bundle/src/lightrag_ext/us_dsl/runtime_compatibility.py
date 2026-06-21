from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from .runtime_config_types import RuntimeConfig
from .runtime_health_checks import FUTURE_REMOTE_STORAGE, SUPPORTED_LOCAL_STORAGE

EXTENSION_SCHEMA_VERSION = "runtime-closure.v1"


def generate_compatibility_matrix(config: RuntimeConfig, *, repo_root: Path | None = None) -> dict[str, Any]:
    root = repo_root or Path.cwd()
    commit = _git(root, ["rev-parse", "HEAD"])
    return {
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "lightrag_commit": commit or "unknown",
        "lightrag_version": "local-fork",
        "extension_schema_version": EXTENSION_SCHEMA_VERSION,
        "sidecar_schema_version": config.sidecar_schema_version,
        "embedding_dimension": config.embedding_dimension,
        "supported_local_storage_backends": sorted(SUPPORTED_LOCAL_STORAGE),
        "future_remote_storage_adapters": sorted(FUTURE_REMOTE_STORAGE),
        "ontology_version": config.ontology_version,
        "term_registry_version": config.term_registry_version,
        "version_policy_version": config.version_policy_version,
        "fusion_policy_version": config.fusion_policy_version,
        "quality_gate_version": config.quality_gate_version,
    }


def validate_compatibility(matrix: dict[str, Any], expected: dict[str, Any] | None = None) -> dict[str, Any]:
    expected = expected or {}
    blockers = []
    for key, value in expected.items():
        if matrix.get(key) != value:
            blockers.append({"field": key, "expected": value, "actual": matrix.get(key)})
    return {
        "readiness": not blockers,
        "status": "READY" if not blockers else "MIGRATION_BLOCKED_INCOMPATIBLE_RUNTIME",
        "blockers": blockers,
    }


def _git(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, timeout=30, check=False)
    except Exception:
        return ""
    return result.stdout.strip()
