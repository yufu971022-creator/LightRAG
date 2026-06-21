from __future__ import annotations

import pytest

from lightrag_ext.us_dsl.harness_state_machine import HarnessStateMachine


def test_valid_state_transitions() -> None:
    machine = HarnessStateMachine()
    machine.transition("PROFILED", event="profile", reason="ok")
    machine.transition("ROUTED", event="route", reason="ok")
    machine.transition("CONTEXT_READY", event="context", reason="ok")
    machine.transition("PLAN_READY", event="plan", reason="ok")
    assert machine.state == "PLAN_READY"
    assert len(machine.transitions) == 4


def test_invalid_state_transition_is_rejected() -> None:
    machine = HarnessStateMachine()
    with pytest.raises(ValueError):
        machine.transition("DRY_RUN_COMPLETED", event="skip", reason="invalid")
