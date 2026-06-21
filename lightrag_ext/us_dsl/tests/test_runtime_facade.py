from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import lightrag_ext.us_dsl.dsl_aware_runtime_facade as facade_module
from lightrag_ext.us_dsl.dsl_aware_runtime_facade import DslAwareRuntimeFacade, capability_scope
from lightrag_ext.us_dsl.runtime_facade_types import RuntimeRequest
from lightrag_ext.us_dsl.tests.engineering_closure_test_helpers import runtime_config


def test_runtime_facade_reuses_existing_orchestrator(monkeypatch, tmp_path: Path) -> None:
    called = {"count": 0}

    def fake_run(request, *, repo_root=None):
        called["count"] += 1
        return SimpleNamespace(final_state="CLEANED_UP", documents=[], queries=[], quality_summary={}, lifecycle={}, __dict__={})

    monkeypatch.setattr(facade_module, "run_unified_e2e", fake_run)
    result = DslAwareRuntimeFacade(runtime_config(), repo_root=Path.cwd()).ingest_documents({"workspace_root": str(tmp_path)})
    assert called["count"] == 1
    assert result.status == "CLEANED_UP"


def test_runtime_facade_does_not_duplicate_algorithms() -> None:
    source = inspect.getsource(facade_module.DslAwareRuntimeFacade)
    assert "execute_document_flow" not in source
    assert "execute_query_quality_flow" not in source
    assert "run_unified_e2e" in source


def test_runtime_facade_exposes_only_in_scope_capabilities() -> None:
    capabilities = capability_scope()
    assert capabilities["functional_qa_available"] is True
    assert capabilities["impact_analysis_available"] is True
    assert capabilities["us_generation_available"] is False
    assert capabilities["code_agent_available"] is False


def test_us_ac_ux_endpoints_do_not_exist() -> None:
    facade = DslAwareRuntimeFacade(runtime_config())
    assert not hasattr(facade, "generate_us")
    assert not hasattr(facade, "generate_ac")
    assert not hasattr(facade, "generate_ux")


def test_facade_propagates_trace_ids(monkeypatch) -> None:
    captured = {}

    def fake_run(request, *, repo_root=None):
        captured["trace_id"] = request.trace_id
        captured["run_id"] = request.run_id
        return SimpleNamespace(final_state="CLEANED_UP", documents=[], queries=[], quality_summary={}, lifecycle={}, __dict__={})

    monkeypatch.setattr(facade_module, "run_unified_e2e", fake_run)
    request = RuntimeRequest("ingest_documents", trace_id="trace-a", run_id="run-a", batch_id="batch-a")
    result = DslAwareRuntimeFacade(runtime_config()).ingest_documents(request)
    assert result.trace_id == "trace-a"
    assert result.run_id == "run-a"
    assert captured == {"trace_id": "trace-a", "run_id": "run-a"}
