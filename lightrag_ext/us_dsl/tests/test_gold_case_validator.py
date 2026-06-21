from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.gold_case_validator import load_cases_for_manifest, validate_gold_cases, valid_cases
from lightrag_ext.us_dsl.tests.multi_module_eval_test_helpers import case_obj, write_manifest_tree


def test_case_ids_are_unique(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    cases.append(cases[0])
    report = validate_gold_cases(manifest, cases)
    assert cases[0].case_id in report.duplicate_case_ids
    assert report.invalid_gold_case_count >= 2


def test_gold_source_refs_are_resolvable(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    cases = load_cases_for_manifest(manifest)
    report = validate_gold_cases(manifest, cases)
    assert report.invalid_gold_case_count == 0
    assert report.valid_case_count == len(cases)


def test_invalid_gold_is_not_counted_as_pass(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path)
    bad_case = case_obj(doc_path=str(tmp_path / "missing.md"))
    report = validate_gold_cases(manifest, [bad_case])
    assert report.invalid_gold_case_count == 1
    assert valid_cases([bad_case], report) == []
