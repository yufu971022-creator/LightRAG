from __future__ import annotations

from lightrag_ext.us_dsl.runtime_feature_flags import SAFE_FLAG_DEFAULTS, resolve_feature_flags, safe_defaults_report


def test_safe_feature_flag_defaults() -> None:
    assert SAFE_FLAG_DEFAULTS["DSL_AWARE_RUNTIME_ENABLED"] is False
    assert SAFE_FLAG_DEFAULTS["PFSS_WRITE_ENABLED"] is False
    assert SAFE_FLAG_DEFAULTS["GENERIC_GRAPH_ENABLED"] is False


def test_live_flags_are_disabled_by_default() -> None:
    report = safe_defaults_report()
    assert report["live_flags_disabled_by_default"] is True
    assert SAFE_FLAG_DEFAULTS["LIVE_UPLOAD_INTEGRATION_ENABLED"] is False
    assert SAFE_FLAG_DEFAULTS["LIVE_QUERY_INTEGRATION_ENABLED"] is False


def test_invalid_flag_dependency_is_blocked() -> None:
    resolution = resolve_feature_flags(cli_overrides={"PFSS_WRITE_ENABLED": True})
    assert "PFSS_WRITE_REQUIRES_DSL_AWARE_RUNTIME" in resolution.violations


def test_config_is_module_agnostic() -> None:
    text = repr(SAFE_FLAG_DEFAULTS).lower()
    assert "bank status" not in text
    assert "swift code" not in text
