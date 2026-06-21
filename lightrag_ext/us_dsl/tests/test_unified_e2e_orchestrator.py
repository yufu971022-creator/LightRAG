from __future__ import annotations

from pathlib import Path

import pytest

from lightrag_ext.us_dsl.unified_e2e_orchestrator import run_unified_e2e
from lightrag_ext.us_dsl.unified_e2e_state_machine import UnifiedE2EStateMachine
from lightrag_ext.us_dsl.tests.unified_e2e_test_helpers import request, run


def test_unified_e2e_orchestrator_completes_with_cleanup(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.final_state == "CLEANED_UP"
    assert result.final_business_state in {"COMPLETED", "COMPLETED_WITH_GAPS"}


def test_adapters_reuse_existing_quality_components(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.quality_summary["functional_qa"]["case_count"] >= 3
    assert result.quality_summary["impact_analysis"]["case_count"] >= 3


def test_unified_trace_ids_are_shared(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.trace_events
    assert {event["trace_id"] for event in result.trace_events} == {result.request.trace_id}


def test_preflight_blocks_max_attempts_above_two(tmp_path: Path) -> None:
    result = run_unified_e2e(request(tmp_path, max_attempts=3), repo_root=Path.cwd())
    assert result.final_state == "FAILED"


def test_invalid_state_transition_is_rejected() -> None:
    machine = UnifiedE2EStateMachine()
    with pytest.raises(ValueError):
        machine.transition("COMPLETED", "invalid jump")
