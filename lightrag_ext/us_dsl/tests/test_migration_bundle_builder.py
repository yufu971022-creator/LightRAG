from __future__ import annotations

from pathlib import Path

import pytest

from lightrag_ext.us_dsl.migration_bundle_builder import (
    REQUIRED_BUNDLE_DIRS,
    REQUIRED_BUNDLE_FILES,
    build_migration_bundle,
    compare_two_builds,
)
from lightrag_ext.us_dsl.migration_bundle_validator import validate_bundle


@pytest.fixture(scope="module")
def built_bundle(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("bundle_builder")
    result = build_migration_bundle(output, repo_root=Path.cwd())
    return result, output


def test_bundle_contains_required_files(built_bundle) -> None:
    result, _ = built_bundle
    bundle = Path(result.bundle_path)
    for name in REQUIRED_BUNDLE_FILES:
        assert (bundle / name).exists(), name
    for name in REQUIRED_BUNDLE_DIRS:
        assert (bundle / name).is_dir(), name


def test_bundle_excludes_git_env_and_real_data(built_bundle) -> None:
    result, _ = built_bundle
    files = [path.relative_to(result.bundle_path).as_posix() for path in Path(result.bundle_path).rglob("*")]
    assert not any(".git" in item for item in files)
    assert not any(item.endswith(".env") for item in files)
    assert not any("LC_Acceptable" in item for item in files)


def test_bundle_excludes_local_indexes(built_bundle) -> None:
    result, _ = built_bundle
    assert result.security_scan["local_index_file_count"] == 0


def test_bundle_contains_no_secrets(built_bundle) -> None:
    result, _ = built_bundle
    assert result.security_scan["secret_hit_count"] == 0


def test_bundle_contains_no_absolute_user_paths(built_bundle) -> None:
    result, _ = built_bundle
    assert result.security_scan["user_absolute_path_hit_count"] == 0


def test_bundle_checksums_validate(built_bundle) -> None:
    result, _ = built_bundle
    report = validate_bundle(result.bundle_path)
    assert report["checksums"]["valid"] is True
    assert report["valid"] is True


def test_two_builds_are_reproducible(built_bundle) -> None:
    result, output = built_bundle
    second = build_migration_bundle(output, repo_root=Path.cwd(), bundle_name="second_bundle")
    report = compare_two_builds(Path(result.bundle_path), Path(second.bundle_path))
    assert report["two_build_file_set_equal"] is True
    assert report["two_build_content_checksum_equal"] is True
