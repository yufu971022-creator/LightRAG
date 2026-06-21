from __future__ import annotations

from lightrag_ext.us_dsl.design_output_quality_harness import evaluate_quality_gates
from lightrag_ext.us_dsl.evidence_citation_gate import evaluate_evidence_citation
from lightrag_ext.us_dsl.targeted_repair_planner import apply_repair, plan_targeted_repair
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import duplicate_impact_output, impact_with_bad_path, qa_case, unsupported_fact_output
from lightrag_ext.us_dsl.functional_qa_executor import execute_functional_qa


def test_repair_planner_targets_failed_gate_only() -> None:
    gate = evaluate_evidence_citation(unsupported_fact_output())
    plan = plan_targeted_repair("case", [gate], attempt_number=1)
    assert {action.target_gate for action in plan.actions} == {"EVIDENCE_CITATION"}


def test_repair_removes_unsupported_claim() -> None:
    output = unsupported_fact_output()
    plan = plan_targeted_repair("case", evaluate_quality_gates(output), attempt_number=1)
    repaired = apply_repair(output, plan)
    assert repaired.supporting_facts == []


def test_repair_adds_version_warning() -> None:
    output = execute_functional_qa(qa_case())
    output = output.__class__(**{**output.__dict__, "version_context": {"resolution_status": "VERSION_REVIEW_REQUIRED", "version_warnings": []}})
    plan = plan_targeted_repair("case", evaluate_quality_gates(output), attempt_number=1)
    repaired = apply_repair(output, plan)
    assert repaired.version_context["version_warnings"]


def test_repair_downgrades_unsupported_impact() -> None:
    output = impact_with_bad_path()
    plan = plan_targeted_repair("case", evaluate_quality_gates(output), attempt_number=1)
    repaired = apply_repair(output, plan)
    assert repaired.direct_impacts == []


def test_max_attempt_count_is_two() -> None:
    plan = plan_targeted_repair("case", evaluate_quality_gates(unsupported_fact_output()), attempt_number=1, max_attempts=2)
    assert plan.attempt_number == 2
    assert plan.max_attempts == 2


def test_second_failure_stops_without_loop() -> None:
    plan = plan_targeted_repair("case", evaluate_quality_gates(unsupported_fact_output()), attempt_number=2, max_attempts=2)
    assert plan.actions == []


def test_repair_merges_duplicate_impact() -> None:
    output = duplicate_impact_output()
    plan = plan_targeted_repair("case", evaluate_quality_gates(output), attempt_number=1)
    repaired = apply_repair(output, plan)
    assert len(repaired.direct_impacts) == 1
