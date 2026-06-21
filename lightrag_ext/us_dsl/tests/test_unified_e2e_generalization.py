from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.unified_e2e_generalization_guard import scan_unified_e2e_runtime
from lightrag_ext.us_dsl.tests.unified_e2e_test_helpers import run


def test_runtime_has_no_module_branch_or_entity_rule() -> None:
    report = scan_unified_e2e_runtime(Path.cwd())
    assert report.runtime_module_branch_count == 0
    assert report.entity_name_specific_rule_count == 0


def test_runtime_has_no_module_weight_or_skill_rule() -> None:
    report = scan_unified_e2e_runtime(Path.cwd())
    assert report.module_specific_weight_count == 0
    assert report.module_specific_skill_count == 0


def test_runtime_has_no_file_name_logic() -> None:
    report = scan_unified_e2e_runtime(Path.cwd())
    assert report.file_name_controls_runtime_logic_count == 0


def test_anti_hardcode_passes_in_full_run(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.anti_hardcode_report["findings"] == []
