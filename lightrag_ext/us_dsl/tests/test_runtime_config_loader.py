from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.runtime_config_loader import build_config_report, load_runtime_config


def test_config_precedence_cli_env_file_default(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.json"
    config_path.write_text(json.dumps({"namespace": "from_file", "embedding_dimension": 4}), encoding="utf-8")
    config = load_runtime_config(
        config_path,
        env={"DSL_RUNTIME_NAMESPACE": "from_env", "EMBEDDING_DIM": "8"},
        cli_overrides={"namespace": "from_cli"},
    )
    assert config.namespace == "from_cli"
    assert config.embedding_dimension == 8
    assert config.config_sources["namespace"] == "cli"
    assert config.config_sources["embedding_dimension"] == "env"


def test_secrets_are_never_returned_by_config_report(tmp_path: Path) -> None:
    config_path = tmp_path / "runtime.json"
    config_path.write_text(json.dumps({"models": {"api_key": "do-not-print"}}), encoding="utf-8")
    report = build_config_report(load_runtime_config(config_path)).to_dict()
    text = json.dumps(report)
    assert "do-not-print" not in text
    assert report["secrets"]["models.api_key"]["configured"] is True


def test_unreplaced_placeholders_block_readiness() -> None:
    from lightrag_ext.us_dsl.runtime_health_checks import evaluate_readiness

    readiness = evaluate_readiness(load_runtime_config())
    assert readiness.status == "NOT_READY_CONFIG"
    assert "UNREPLACED_PLACEHOLDER_CONFIG" in readiness.reason_codes


def test_config_is_module_agnostic(tmp_path: Path) -> None:
    config = load_runtime_config(tmp_path / "missing.json") if False else load_runtime_config()
    text = json.dumps(config.to_dict()).lower()
    assert "acceptable_bank" not in text
    assert "lc_" not in text
