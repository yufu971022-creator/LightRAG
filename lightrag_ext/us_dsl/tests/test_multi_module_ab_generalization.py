from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.gold_case_validator import load_cases_for_manifest
from lightrag_ext.us_dsl.multi_module_ab_generalization_guard import inspect_multi_module_runtime_hardcoding
from lightrag_ext.us_dsl.tests.multi_module_eval_test_helpers import write_manifest_tree


def test_runtime_has_no_manifest_module_branch(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    runtime = tmp_path / "runtime.py"
    runtime.write_text('def f(module_code):\n    return module_code\n', encoding="utf-8")
    report = inspect_multi_module_runtime_hardcoding(manifest=manifest, cases=cases, runtime_roots=[runtime])
    assert report.runtime_module_branch_count == 0


def test_runtime_has_no_entity_name_specific_weight(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    runtime = tmp_path / "runtime.py"
    entity = cases[0].gold_semantic_object_ids[0]
    runtime.write_text(f'def f(entity_name):\n    if entity_name == "{entity}":\n        weight = 2\n    return weight\n', encoding="utf-8")
    report = inspect_multi_module_runtime_hardcoding(manifest=manifest, cases=cases, runtime_roots=[runtime])
    assert report.entity_name_specific_weight_rule_count == 1


def test_holdout_specific_rule_count_is_zero(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    runtime = tmp_path / "runtime.py"
    runtime.write_text('def f(module_code):\n    return "ok"\n', encoding="utf-8")
    report = inspect_multi_module_runtime_hardcoding(manifest=manifest, cases=cases, runtime_roots=[runtime])
    assert report.holdout_specific_rule_count == 0


def test_new_module_requires_config_not_code_change(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path, module_count=5, include_holdout=True, domains=6)
    cases = load_cases_for_manifest(manifest)
    runtime = tmp_path / "runtime.py"
    runtime.write_text('def f(config):\n    return config.get("module_code")\n', encoding="utf-8")
    report = inspect_multi_module_runtime_hardcoding(manifest=manifest, cases=cases, runtime_roots=[runtime])
    assert report.runtime_module_branch_count == 0


def test_fixture_names_are_not_imported_by_runtime(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    runtime = tmp_path / "runtime.py"
    runtime.write_text('from lightrag_ext.us_dsl.tests.multi_module_eval_test_helpers import write_manifest_tree\n', encoding="utf-8")
    report = inspect_multi_module_runtime_hardcoding(manifest=manifest, cases=cases, runtime_roots=[runtime])
    assert report.fixture_runtime_coupling_count == 1
