from __future__ import annotations

from pathlib import Path

import pytest

from lightrag_ext.us_dsl.migration_bundle_builder import build_migration_bundle
from lightrag_ext.us_dsl.portable_bundle_smoke import run_portable_bundle_smoke


@pytest.fixture(scope="module")
def smoke_report(tmp_path_factory: pytest.TempPathFactory):
    output = tmp_path_factory.mktemp("bundle_smoke")
    result = build_migration_bundle(output, repo_root=Path.cwd())
    extract_to = tmp_path_factory.mktemp("bundle_extract") / "portable"
    return run_portable_bundle_smoke(result.bundle_path, extract_to, cleanup=True)


def test_bundle_can_run_outside_source_repo(smoke_report) -> None:
    assert smoke_report["source_repo_dependency_detected"] is False
    assert smoke_report["portable_smoke_passed"] is True


def test_unconfigured_bundle_is_not_ready(smoke_report) -> None:
    assert smoke_report["unconfigured_readiness_status"] == "NOT_READY_CONFIG"


def test_sanitized_bundle_smoke_ingestion(smoke_report) -> None:
    assert smoke_report["ingestion_passed"] is True


def test_sanitized_bundle_smoke_functional_qa(smoke_report) -> None:
    assert smoke_report["functional_qa_passed"] is True


def test_sanitized_bundle_smoke_impact_analysis(smoke_report) -> None:
    assert smoke_report["impact_analysis_passed"] is True


def test_sanitized_bundle_smoke_quality_gate(smoke_report) -> None:
    assert smoke_report["quality_gate_passed"] is True


def test_sanitized_bundle_smoke_lifecycle_rebuild(smoke_report) -> None:
    assert smoke_report["lifecycle_rebuild_passed"] is True


def test_bundle_smoke_uses_no_network_or_real_models(smoke_report) -> None:
    assert smoke_report["network_calls_executed"] is False
    assert smoke_report["real_model_calls_executed"] is False


def test_bundle_smoke_cleanup(smoke_report) -> None:
    assert smoke_report["cleanup_passed"] is True
