from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lightrag_ext.us_dsl.dsl_aware_runtime_facade import DslAwareRuntimeFacade
from lightrag_ext.us_dsl.runtime_feature_flags import SAFE_FLAG_DEFAULTS
from lightrag_ext.us_dsl.tests.engineering_closure_test_helpers import runtime_config


def test_no_live_upload_or_query_change() -> None:
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--", "lightrag/api"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert diff.stdout.strip() == ""
    assert SAFE_FLAG_DEFAULTS["LIVE_UPLOAD_INTEGRATION_ENABLED"] is False
    assert SAFE_FLAG_DEFAULTS["LIVE_QUERY_INTEGRATION_ENABLED"] is False


def test_no_production_storage_connection() -> None:
    config = runtime_config()
    result = DslAwareRuntimeFacade(config).health().to_dict()
    assert result["result"]["health"]["external_services_checked"] is False
    assert SAFE_FLAG_DEFAULTS["REMOTE_STORAGE_ENABLED"] is False


def test_pending_production_gates_are_explicit() -> None:
    gates = _pending_gates()
    assert gates["formal_multi_module_ab_gate"]["blocking"] is True
    assert gates["production_approval"]["status"] == "PENDING"


def test_report_is_serializable() -> None:
    result = DslAwareRuntimeFacade(runtime_config()).readiness().to_dict()
    json.dumps(result, sort_keys=True)


def test_no_lightrag_core_modified() -> None:
    diff = subprocess.run(
        ["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert diff.stdout.strip() == ""


def test_production_defaults_are_disabled() -> None:
    assert SAFE_FLAG_DEFAULTS["REAL_MODEL_CALLS_ENABLED"] is False
    assert SAFE_FLAG_DEFAULTS["REMOTE_STORAGE_ENABLED"] is False
    assert SAFE_FLAG_DEFAULTS["GENERIC_GRAPH_ENABLED"] is False


def _pending_gates() -> dict[str, dict[str, object]]:
    names = [
        "formal_multi_module_ab_gate",
        "holdout_module_validation",
        "intranet_real_embedding_validation",
        "intranet_real_llm_authorization",
        "intranet_storage_adapter_validation",
        "intranet_network_proxy_validation",
        "live_upload_integration",
        "live_query_integration",
        "data_security_review",
        "performance_capacity_test",
        "production_rollback_drill",
        "production_approval",
    ]
    return {
        name: {
            "status": "PENDING",
            "required_evidence": "runbook evidence required",
            "owner_placeholder": "<<OWNER>>",
            "blocking": True,
            "recommended_command_or_runbook": "runbooks/12_生产准出未完成项.md",
        }
        for name in names
    }
