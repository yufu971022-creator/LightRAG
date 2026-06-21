from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.local_case_builder import build_local_cases, case_source_report
from lightrag_ext.us_dsl.local_us_inventory import discover_local_us_documents


def _docs(tmp_path: Path):
    (tmp_path / "A_US.md").write_text("# US-1\nField and rule evidence", encoding="utf-8")
    (tmp_path / "A_US_dfx.md").write_text("# US-2\nDFX evidence", encoding="utf-8")
    (tmp_path / "A_US_质检问题高亮版.md").write_text("# US-3\nquality issue", encoding="utf-8")
    return discover_local_us_documents(tmp_path)[0]


def test_gold_and_silver_cases_are_separated(tmp_path: Path) -> None:
    cases = build_local_cases(_docs(tmp_path))
    assert cases["gold_backed"] == []
    assert cases["silver_regression"]
    assert case_source_report(cases)["gold_backed_count"] == 0


def test_llm_generated_cases_are_not_primary_gold(tmp_path: Path) -> None:
    cases = build_local_cases(_docs(tmp_path))
    assert case_source_report(cases)["llm_generated_primary_gold_count"] == 0
