from __future__ import annotations

from pathlib import Path

import pytest

from lightrag_ext.us_dsl.migration_bundle_builder import build_migration_bundle
from lightrag_ext.us_dsl.migration_bundle_validator import validate_bundle


@pytest.fixture(scope="module")
def validation_report(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("bundle_validator")
    result = build_migration_bundle(output, repo_root=Path.cwd())
    return validate_bundle(result.bundle_path)


def test_validator_accepts_valid_bundle(validation_report) -> None:
    assert validation_report["valid"] is True


def test_validator_reports_package_inventory(validation_report) -> None:
    assert validation_report["package_file_count"] > 20
    assert "README.md" in validation_report["package_inventory"]


def test_validator_rejects_missing_required_file(tmp_path: Path) -> None:
    result = build_migration_bundle(tmp_path, repo_root=Path.cwd())
    (Path(result.bundle_path) / "README.md").unlink()
    report = validate_bundle(result.bundle_path)
    assert report["valid"] is False
    assert "README.md" in report["missing_files"]


def test_validator_security_counts_are_zero(validation_report) -> None:
    security = validation_report["security_scan"]
    assert security["secret_hit_count"] == 0
    assert security["internal_endpoint_hit_count"] == 0


def test_validator_anti_hardcode_counts_are_zero(validation_report) -> None:
    anti = validation_report["anti_hardcode"]
    assert anti["runtime_module_branch_count"] == 0
    assert anti["module_specific_skill_count"] == 0
