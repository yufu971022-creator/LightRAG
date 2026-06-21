from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.entity_type_generalization_guard import scan_runtime_files, summarize_relation_signature_generalization
from lightrag_ext.us_dsl.relation_type_signature_registry import default_relation_type_signature_registry


def _report():
    return scan_runtime_files(Path.cwd())


def test_runtime_resolver_has_no_acceptable_bank_hardcode() -> None:
    report = _report().to_dict()
    serialized = str(report)
    assert "Acceptable Bank" not in serialized
    assert "可接受银行" not in serialized
    assert "Bank Status" not in serialized


def test_runtime_resolver_has_no_inquiry_hardcode() -> None:
    report = _report().to_dict()
    serialized = str(report)
    assert "询价项目" not in serialized
    assert "询价项目列表" not in serialized


def test_runtime_resolver_has_no_fx_or_other_module_hardcode() -> None:
    report = _report().to_dict()
    serialized = str(report)
    for term in ["LCAB", "FX", "外汇", "现金池", "账户", "资金计划", "付款"]:
        assert term not in serialized


def test_runtime_resolver_does_not_reference_fixture_names() -> None:
    report = _report()
    assert report.fixture_reference_hits == []
    assert report.runtime_test_coupling_hits == []


def test_relation_signatures_are_type_based_not_name_based() -> None:
    report = summarize_relation_signature_generalization(default_relation_type_signature_registry().to_report())
    assert report.signature_count > 0
    assert report.name_specific_signature_count == 0
    assert report.module_specific_signature_count == 0
    assert report.type_based_signature_count == report.signature_count


def test_anti_hardcode_guard_ignores_test_fixtures_but_checks_runtime_logic(tmp_path: Path) -> None:
    runtime_file = tmp_path / "runtime.py"
    runtime_file.write_text('def f(entity_name):\n    if "Bank Status" in entity_name:\n        return "FieldSpec"\n', encoding="utf-8")
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_fixture.py"
    test_file.write_text('SAMPLE = "Bank Status"\n', encoding="utf-8")
    report = scan_runtime_files(tmp_path, ["runtime.py", "tests/test_fixture.py"])
    assert len(report.conditional_business_term_hits) == 1
    assert report.files_scanned == ["runtime.py"]
