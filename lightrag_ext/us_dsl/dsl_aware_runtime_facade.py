from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from .runtime_config_loader import build_config_report, load_runtime_config
from .runtime_config_types import RuntimeConfig, to_plain_dict
from .runtime_facade_types import RuntimeRequest, RuntimeResult
from .runtime_health_checks import evaluate_readiness, health
from .runtime_metrics import RuntimeMetrics
from .runtime_observability import StructuredRuntimeLogger
from .unified_e2e_orchestrator import run_unified_e2e
from .unified_e2e_types import UnifiedDocumentInput, UnifiedE2ERequest, UnifiedQueryInput, UnifiedRequirementInput

OUT_OF_SCOPE_CAPABILITIES = {
    "us_generation_available": False,
    "ac_generation_available": False,
    "ux_generation_available": False,
    "code_agent_available": False,
}


class DslAwareRuntimeFacade:
    def __init__(self, config: RuntimeConfig | None = None, *, repo_root: Path | None = None) -> None:
        self.config = config or load_runtime_config()
        self.repo_root = repo_root or Path.cwd()
        self.logger = StructuredRuntimeLogger()
        self.metrics = RuntimeMetrics()

    def preflight(self, request: RuntimeRequest | dict[str, Any] | None = None) -> RuntimeResult:
        resolved = self._request("preflight", request)
        readiness = evaluate_readiness(self.config)
        config_report = build_config_report(self.config).to_dict()
        return self._result(resolved, "READY" if readiness.ready else readiness.status, {"readiness": readiness.to_dict(), "config_report": config_report}, readiness.reason_codes)

    def ingest_documents(self, request: RuntimeRequest | dict[str, Any]) -> RuntimeResult:
        resolved = self._request("ingest_documents", request)
        run_result = self._execute_e2e(resolved, stage="INGEST")
        for document in run_result.documents:
            self.metrics.record_ingestion(status="FAILED" if document.failed else "OK", route=document.route)
        return self._result(resolved, run_result.final_state, {"e2e": to_plain_dict(run_result), "capabilities": capability_scope()})

    def query_function(self, request: RuntimeRequest | dict[str, Any]) -> RuntimeResult:
        resolved = self._request("query_function", request)
        run_result = self._execute_e2e(resolved, stage="QUERY")
        for query in run_result.queries:
            self.metrics.record_query(status=query.final_state, scenario="generic")
        return self._result(resolved, run_result.final_state, {"e2e": to_plain_dict(run_result)})

    def analyze_impact(self, request: RuntimeRequest | dict[str, Any]) -> RuntimeResult:
        resolved = self._request("analyze_impact", request)
        run_result = self._execute_e2e(resolved, stage="IMPACT")
        self.metrics.record_quality_safety(status="OK", gate="impact_analysis")
        return self._result(resolved, run_result.final_state, {"e2e": to_plain_dict(run_result)})

    def update_document_version(self, request: RuntimeRequest | dict[str, Any]) -> RuntimeResult:
        return self._lifecycle_result("update_document_version", request)

    def delete_document_version(self, request: RuntimeRequest | dict[str, Any]) -> RuntimeResult:
        return self._lifecycle_result("delete_document_version", request)

    def delete_document(self, request: RuntimeRequest | dict[str, Any]) -> RuntimeResult:
        return self._lifecycle_result("delete_document", request)

    def rebuild_document_version(self, request: RuntimeRequest | dict[str, Any]) -> RuntimeResult:
        return self._lifecycle_result("rebuild_document_version", request)

    def health(self) -> RuntimeResult:
        request = self._request("health", None)
        return self._result(request, "HEALTHY", {"health": health(self.config).to_dict()})

    def readiness(self) -> RuntimeResult:
        request = self._request("readiness", None)
        readiness = evaluate_readiness(self.config)
        return self._result(request, "READY" if readiness.ready else readiness.status, {"readiness": readiness.to_dict()}, readiness.reason_codes)

    def diagnostics(self, request: RuntimeRequest | dict[str, Any] | None = None) -> RuntimeResult:
        resolved = self._request("diagnostics", request)
        return self._result(resolved, "OK", {"logs": self.logger.to_list(), "metrics": self.metrics.snapshot(), "capabilities": capability_scope()})

    def _lifecycle_result(self, operation: str, request: RuntimeRequest | dict[str, Any]) -> RuntimeResult:
        resolved = self._request(operation, request)
        run_result = self._execute_e2e(resolved, stage="LIFECYCLE")
        self.metrics.record_quality_safety(status="OK", gate=operation)
        return self._result(resolved, run_result.final_state, {"lifecycle": to_plain_dict(run_result.lifecycle), "e2e": to_plain_dict(run_result)})

    def _execute_e2e(self, request: RuntimeRequest, *, stage: str):
        payload = request.payload
        e2e_request = UnifiedE2ERequest(
            run_id=request.run_id or _id("run"),
            trace_id=request.trace_id or _id("trace"),
            mode="LOCAL_ISOLATED",
            document_inputs=_documents(payload),
            query_inputs=_queries(payload),
            requirement_inputs=_requirements(payload),
            evaluation_case_refs=list(payload.get("evaluation_case_refs", [])),
            artifact_root=str(payload.get("artifact_root", "artifacts/block_28b_engineering_closure")),
            workspace_root=str(payload.get("workspace_root", "artifacts/block_28b_engineering_closure/workspaces/runtime_facade")),
            cleanup_after_run=bool(payload.get("cleanup_after_run", True)),
            enable_lifecycle_scenarios=True,
            enable_functional_qa=bool(self.config.feature_flags.get("FUNCTIONAL_QA_ENABLED", True)),
            enable_impact_analysis=bool(self.config.feature_flags.get("IMPACT_ANALYSIS_ENABLED", True)),
            enable_quality_gate=bool(self.config.feature_flags.get("QUALITY_GATE_ENABLED", True)),
            max_attempts=int(payload.get("max_attempts", 2)),
        )
        self.logger.emit(
            trace_id=e2e_request.trace_id,
            run_id=e2e_request.run_id,
            batch_id=request.batch_id or _id("batch"),
            stage=stage,
            component="DslAwareRuntimeFacade",
            event="dispatch_unified_e2e",
        )
        return run_unified_e2e(e2e_request, repo_root=self.repo_root)

    def _request(self, operation: str, request: RuntimeRequest | dict[str, Any] | None) -> RuntimeRequest:
        if isinstance(request, RuntimeRequest):
            return RuntimeRequest(operation=operation, payload=request.payload, trace_id=request.trace_id or _id("trace"), run_id=request.run_id or _id("run"), batch_id=request.batch_id or _id("batch"))
        payload = dict(request or {})
        return RuntimeRequest(
            operation=operation,
            payload=payload.get("payload", payload),
            trace_id=payload.get("trace_id") or _id("trace"),
            run_id=payload.get("run_id") or _id("run"),
            batch_id=payload.get("batch_id") or _id("batch"),
        )

    def _result(self, request: RuntimeRequest, status: str, result: dict[str, Any], reason_codes: list[str] | None = None) -> RuntimeResult:
        return RuntimeResult(
            operation=request.operation,
            status=status,
            trace_id=request.trace_id or _id("trace"),
            run_id=request.run_id or _id("run"),
            batch_id=request.batch_id or _id("batch"),
            result=result,
            logs=self.logger.to_list(),
            metrics=self.metrics.snapshot(),
            reason_codes=reason_codes or [],
        )


def capability_scope() -> dict[str, bool]:
    return {
        "ingestion_available": True,
        "functional_qa_available": True,
        "impact_analysis_available": True,
        "lifecycle_available": True,
        **OUT_OF_SCOPE_CAPABILITIES,
    }


def _documents(payload: dict[str, Any]) -> list[UnifiedDocumentInput]:
    documents = payload.get("documents") or [
        {"document_id": "DOC-SAFE-FULL", "route": "DSL_FULL", "content": "Synthetic object behavior.", "source_us_id": "SRC-FULL"},
        {"document_id": "DOC-SAFE-PARTIAL", "route": "DSL_PARTIAL", "content": "Synthetic partial behavior.", "source_us_id": "SRC-PARTIAL"},
        {"document_id": "DOC-SAFE-RAW", "route": "RAW_ONLY", "content": "Synthetic raw evidence.", "source_us_id": "SRC-RAW"},
    ]
    return [
        UnifiedDocumentInput(
            str(item.get("document_id", f"DOC-{index}")),
            item.get("route", "RAW_ONLY"),
            str(item.get("content", "synthetic content")),
            str(item.get("source_us_id", f"SRC-{index}")),
            bool(item.get("parse_should_succeed", True)),
            str(item.get("version_group_key", "vg-generic")),
        )
        for index, item in enumerate(documents, start=1)
    ]


def _queries(payload: dict[str, Any]) -> list[UnifiedQueryInput]:
    queries = payload.get("queries") or [
        {"query_id": "QA-SAFE-1", "query_text": "Summarize confirmed behavior.", "scenario": "ONE_TO_MANY", "expected_answer_status": "ANSWERED_WITH_CONFIRMED_EVIDENCE"},
        {"query_id": "QA-SAFE-2", "query_text": "Show text-only fallback.", "scenario": "ONE_TO_ONE_X", "expected_answer_status": "TEXT_ONLY_EVIDENCE"},
    ]
    return [
        UnifiedQueryInput(
            str(item.get("query_id", f"QA-{index}")),
            str(item.get("query_text", "synthetic question")),
            str(item.get("scenario", "ONE_TO_MANY")),
            str(item.get("expected_answer_status", "ANSWERED_WITH_CONFIRMED_EVIDENCE")),
        )
        for index, item in enumerate(queries, start=1)
    ]


def _requirements(payload: dict[str, Any]) -> list[UnifiedRequirementInput]:
    requirements = payload.get("requirements") or [
        {"requirement_id": "REQ-SAFE-1", "requirement_text": "Synthetic change.", "scenario": "ONE_TO_MANY"}
    ]
    return [
        UnifiedRequirementInput(
            str(item.get("requirement_id", f"REQ-{index}")),
            str(item.get("requirement_text", "synthetic requirement")),
            str(item.get("scenario", "ONE_TO_MANY")),
        )
        for index, item in enumerate(requirements, start=1)
    ]


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
