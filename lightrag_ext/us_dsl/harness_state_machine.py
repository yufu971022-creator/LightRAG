from __future__ import annotations

from datetime import UTC, datetime

from .harness_types import HarnessState, StateTransition

ALLOWED_TRANSITIONS: dict[HarnessState, set[HarnessState]] = {
    "CREATED": {"PROFILED", "FAILED", "CANCELLED"},
    "PROFILED": {"ROUTED", "BLOCKED_BY_INSUFFICIENT_EVIDENCE", "FAILED", "CANCELLED"},
    "ROUTED": {"WAITING_FOR_CLARIFICATION", "CONTEXT_READY", "BLOCKED_BY_INSUFFICIENT_EVIDENCE", "FAILED", "CANCELLED"},
    "WAITING_FOR_CLARIFICATION": {"CANCELLED"},
    "CONTEXT_READY": {"PLAN_READY", "CHECKPOINT_BLOCKED", "BLOCKED_BY_MISSING_CAPABILITY", "BLOCKED_BY_INSUFFICIENT_EVIDENCE", "FAILED", "CANCELLED"},
    "PLAN_READY": {"EXECUTING", "CANCELLED"},
    "EXECUTING": {"DRY_RUN_COMPLETED", "CHECKPOINT_BLOCKED", "BLOCKED_BY_MISSING_CAPABILITY", "FAILED", "CANCELLED"},
    "CHECKPOINT_BLOCKED": {"BLOCKED_BY_MISSING_CAPABILITY", "BLOCKED_BY_INSUFFICIENT_EVIDENCE", "CANCELLED"},
    "BLOCKED_BY_MISSING_CAPABILITY": {"CANCELLED"},
    "BLOCKED_BY_INSUFFICIENT_EVIDENCE": {"CANCELLED"},
    "DRY_RUN_COMPLETED": {"CANCELLED"},
    "FAILED": {"CANCELLED"},
    "CANCELLED": set(),
}


class HarnessStateMachine:
    def __init__(self) -> None:
        self.state: HarnessState = "CREATED"
        self.transitions: list[StateTransition] = []

    def transition(self, to_state: HarnessState, *, event: str, reason: str, actor: str = "SYSTEM") -> StateTransition:
        allowed = ALLOWED_TRANSITIONS[self.state]
        if to_state not in allowed:
            raise ValueError(f"invalid transition {self.state} -> {to_state}")
        transition = StateTransition(
            from_state=self.state,
            to_state=to_state,
            event=event,
            reason=reason,
            timestamp=datetime.now(UTC).isoformat(),
            actor=actor,
        )
        self.transitions.append(transition)
        self.state = to_state
        return transition
