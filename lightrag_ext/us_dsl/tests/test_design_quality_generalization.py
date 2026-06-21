from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.design_quality_generalization_guard import scan_design_quality_runtime
from lightrag_ext.us_dsl.design_quality_types import DesignQualityCase
from lightrag_ext.us_dsl.design_output_quality_harness import run_design_quality_case


def test_runtime_has_no_module_specific_quality_rule() -> None:
    report = scan_design_quality_runtime(Path.cwd())
    assert report.runtime_module_branch_count == 0
    assert report.module_specific_dimension_rule_count == 0


def test_runtime_has_no_entity_name_specific_gate() -> None:
    report = scan_design_quality_runtime(Path.cwd())
    assert report.entity_name_quality_rule_count == 0


def test_holdout_module_uses_same_gate() -> None:
    case = DesignQualityCase("HOLDOUT", "SILVER", "IMPACT_ANALYSIS", "ONE_TO_MANY", "Unseen module impact", "QUALITY_GATE_PASSED", metadata={"module_code": "UNSEEN"})
    result = run_design_quality_case(case)
    assert result.final_state == "QUALITY_GATE_PASSED"
