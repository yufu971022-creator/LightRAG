from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.runtime_security_guard import scan_final_anti_hardcode, scan_security


def test_security_scan_detects_secret_patterns(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.txt"
    path.write_text("Authorization: Bearer abcdefghijklmnop", encoding="utf-8")
    report = scan_security(tmp_path).to_dict()
    assert report["secret_hit_count"] == 1


def test_security_scan_allows_placeholder_templates(tmp_path: Path) -> None:
    path = tmp_path / "template.txt"
    path.write_text("endpoint: <<LLM_API_BASE>>\ncredential: <<API_KEY>>\n", encoding="utf-8")
    report = scan_security(tmp_path).to_dict()
    assert report["secret_hit_count"] == 0
    assert report["internal_endpoint_hit_count"] == 0


def test_final_runtime_has_no_module_hardcode() -> None:
    report = scan_final_anti_hardcode(
        Path.cwd() / "lightrag_ext/us_dsl",
        files=[Path("runtime_feature_flags.py"), Path("dsl_aware_runtime_facade.py")],
    )
    assert report["runtime_module_branch_count"] == 0
    assert report["entity_name_specific_rule_count"] == 0
