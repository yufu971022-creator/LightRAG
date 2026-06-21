from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.unified_e2e_orchestrator import run_unified_e2e
from lightrag_ext.us_dsl.unified_e2e_types import UnifiedDocumentInput, UnifiedE2ERequest, UnifiedQueryInput, UnifiedRequirementInput


def request(tmp_path: Path | None = None, *, max_attempts: int = 2) -> UnifiedE2ERequest:
    root = tmp_path or Path("artifacts/block_28a_unified_local_e2e")
    return UnifiedE2ERequest(
        run_id="test-run",
        trace_id="test-trace",
        mode="LOCAL_ISOLATED",
        document_inputs=[
            UnifiedDocumentInput("DOC-FULL", "DSL_FULL", "full", "US-FULL"),
            UnifiedDocumentInput("DOC-PARTIAL", "DSL_PARTIAL", "partial", "US-PARTIAL"),
            UnifiedDocumentInput("DOC-RAW", "RAW_ONLY", "raw", "US-RAW"),
            UnifiedDocumentInput("DOC-FAIL", "PARSE_FAILED", "bad", "US-FAIL", parse_should_succeed=False),
        ],
        query_inputs=[
            UnifiedQueryInput("QA-CONFIRMED", "Confirmed", "ONE_TO_MANY", "ANSWERED_WITH_CONFIRMED_EVIDENCE"),
            UnifiedQueryInput("QA-VERSION", "Version", "ONE_TO_MANY", "ANSWERED_WITH_VERSION_WARNING"),
            UnifiedQueryInput("QA-TEXT", "Text", "ONE_TO_ONE_X", "TEXT_ONLY_EVIDENCE"),
        ],
        requirement_inputs=[
            UnifiedRequirementInput("REQ-1N", "Many", "ONE_TO_MANY"),
            UnifiedRequirementInput("REQ-LOCAL", "Local", "ONE_TO_ONE_X"),
            UnifiedRequirementInput("REQ-ZERO", "Zero", "ZERO_TO_ONE"),
        ],
        evaluation_case_refs=[],
        artifact_root=str(root),
        workspace_root=str(root / "workspaces" / "test-run"),
        cleanup_after_run=True,
        enable_lifecycle_scenarios=True,
        enable_functional_qa=True,
        enable_impact_analysis=True,
        enable_quality_gate=True,
        max_attempts=max_attempts,
    )


def run(tmp_path: Path | None = None):
    return run_unified_e2e(request(tmp_path), repo_root=Path.cwd())
