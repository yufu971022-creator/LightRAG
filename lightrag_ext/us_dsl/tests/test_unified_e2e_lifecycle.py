from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.tests.unified_e2e_test_helpers import run


def test_lifecycle_initial_update_delete_rebuild(tmp_path: Path) -> None:
    lifecycle = run(tmp_path).lifecycle
    assert lifecycle.initial_ingestion_passed
    assert lifecycle.version_update_passed
    assert lifecycle.delete_passed
    assert lifecycle.rebuild_passed


def test_failure_compensation_passed(tmp_path: Path) -> None:
    assert run(tmp_path).lifecycle.compensation_passed


def test_active_version_consistency_passed(tmp_path: Path) -> None:
    assert run(tmp_path).lifecycle.active_version_consistency_passed


def test_no_new_supersedes_created(tmp_path: Path) -> None:
    assert run(tmp_path).lifecycle.new_supersedes_created is False
