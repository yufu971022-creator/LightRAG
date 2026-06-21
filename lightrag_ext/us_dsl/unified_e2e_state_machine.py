from __future__ import annotations

from datetime import UTC, datetime

from .unified_e2e_types import UnifiedE2EState

ALLOWED_TRANSITIONS: dict[UnifiedE2EState, set[UnifiedE2EState]] = {
    "CREATED": {"PREFLIGHT_VALIDATED", "FAILED"},
    "PREFLIGHT_VALIDATED": {"DOCUMENTS_DISCOVERED", "FAILED"},
    "DOCUMENTS_DISCOVERED": {"PARSING", "FAILED"},
    "PARSING": {"RAW_EVIDENCE_INDEXED", "FAILED", "COMPENSATING"},
    "RAW_EVIDENCE_INDEXED": {"ROUTED", "FAILED", "COMPENSATING"},
    "ROUTED": {"DSL_COMPILED", "FAILED", "COMPENSATING"},
    "DSL_COMPILED": {"SEMANTIC_BRANCH_WRITTEN", "FAILED", "COMPENSATING"},
    "SEMANTIC_BRANCH_WRITTEN": {"SIDECAR_PERSISTED", "FAILED", "COMPENSATING"},
    "SIDECAR_PERSISTED": {"LIFECYCLE_VALIDATED", "FAILED", "COMPENSATING"},
    "LIFECYCLE_VALIDATED": {"QUERY_CONTEXT_READY", "FAILED"},
    "QUERY_CONTEXT_READY": {"FUNCTIONAL_QA_EXECUTED", "FAILED"},
    "FUNCTIONAL_QA_EXECUTED": {"IMPACT_ANALYSIS_EXECUTED", "FAILED"},
    "IMPACT_ANALYSIS_EXECUTED": {"QUALITY_GATE_CHECKED", "FAILED"},
    "QUALITY_GATE_CHECKED": {"COMPLETED", "COMPLETED_WITH_GAPS", "FAILED"},
    "COMPLETED": {"CLEANED_UP"},
    "COMPLETED_WITH_GAPS": {"CLEANED_UP"},
    "FAILED": {"COMPENSATING", "CLEANED_UP"},
    "COMPENSATING": {"COMPENSATED", "FAILED"},
    "COMPENSATED": {"CLEANED_UP"},
    "CLEANED_UP": set(),
}


class UnifiedE2EStateMachine:
    def __init__(self) -> None:
        self.state: UnifiedE2EState = "CREATED"
        self.transitions: list[dict[str, str]] = []

    def transition(self, to_state: UnifiedE2EState, reason: str) -> None:
        if to_state not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"invalid unified e2e transition {self.state} -> {to_state}")
        self.transitions.append(
            {
                "from_state": self.state,
                "to_state": to_state,
                "reason": reason,
                "timestamp": datetime.now(UTC).isoformat(),
                "actor": "SYSTEM",
            }
        )
        self.state = to_state
