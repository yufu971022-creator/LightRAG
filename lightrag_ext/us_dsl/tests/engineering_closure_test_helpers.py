from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.runtime_config_types import RuntimeConfig
from lightrag_ext.us_dsl.runtime_feature_flags import SAFE_FLAG_DEFAULTS


def runtime_config(**overrides):
    flags = dict(SAFE_FLAG_DEFAULTS)
    flags.update(
        {
            "DSL_AWARE_RUNTIME_ENABLED": True,
            "REAL_MODEL_CALLS_ENABLED": False,
            "REMOTE_STORAGE_ENABLED": False,
            "LIVE_UPLOAD_INTEGRATION_ENABLED": False,
            "LIVE_QUERY_INTEGRATION_ENABLED": False,
        }
    )
    data = {
        "deployment_mode": "LOCAL_ISOLATED",
        "namespace": "local_test_runtime",
        "working_dir": "workspaces/local_test_runtime",
        "module_manifest_path": "sanitized/module_manifest.json",
        "embedding_model": "synthetic-embedding",
        "embedding_dimension": 8,
        "expected_embedding_dimension": 8,
        "llm_model": "synthetic-llm",
        "storage_backend": "LOCAL_JSON",
        "feature_flags": flags,
    }
    data.update(overrides)
    return RuntimeConfig(**data)


def write_config(path: Path, **overrides) -> Path:
    config = runtime_config(**overrides).to_dict()
    path.write_text(__import__("json").dumps(config, sort_keys=True), encoding="utf-8")
    return path
