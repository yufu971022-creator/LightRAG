from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.dsl_aware_runtime_facade import DslAwareRuntimeFacade, capability_scope
from lightrag_ext.us_dsl.runtime_security_guard import scan_final_anti_hardcode
from lightrag_ext.us_dsl.tests.engineering_closure_test_helpers import runtime_config


def test_final_runtime_has_no_module_hardcode() -> None:
    report = scan_final_anti_hardcode(
        Path.cwd() / "lightrag_ext/us_dsl",
        files=[
            Path("runtime_feature_flags.py"),
            Path("runtime_config_loader.py"),
            Path("runtime_health_checks.py"),
            Path("dsl_aware_runtime_facade.py"),
        ],
    )
    assert report["runtime_module_branch_count"] == 0
    assert report["entity_name_specific_rule_count"] == 0
    assert report["module_specific_weight_count"] == 0
    assert report["module_specific_skill_count"] == 0


def test_new_module_requires_only_manifest_and_config() -> None:
    config = runtime_config(module_manifest_path="sanitized/new_module_manifest.json")
    facade = DslAwareRuntimeFacade(config)
    readiness = facade.readiness().to_dict()
    assert readiness["status"] == "READY"
    assert "new_module_manifest" in config.module_manifest_path


def test_no_us_ac_ux_or_code_agent() -> None:
    capabilities = capability_scope()
    assert capabilities["us_generation_available"] is False
    assert capabilities["ac_generation_available"] is False
    assert capabilities["ux_generation_available"] is False
    assert capabilities["code_agent_available"] is False
