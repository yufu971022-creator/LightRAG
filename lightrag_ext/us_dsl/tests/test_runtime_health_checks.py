from __future__ import annotations

from lightrag_ext.us_dsl.runtime_health_checks import evaluate_readiness, health
from lightrag_ext.us_dsl.tests.engineering_closure_test_helpers import runtime_config


def test_health_and_readiness_are_distinct() -> None:
    config = runtime_config(module_manifest_path="<<MODULE_MANIFEST_PATH>>")
    assert health(config).status == "HEALTHY"
    assert evaluate_readiness(config).status == "NOT_READY_CONFIG"


def test_embedding_dimension_mismatch_blocks_readiness() -> None:
    report = evaluate_readiness(runtime_config(embedding_dimension=8, expected_embedding_dimension=16))
    assert report.status == "NOT_READY_MODEL"
    assert "EMBEDDING_DIMENSION_MISMATCH" in report.reason_codes


def test_namespace_collision_blocks_readiness() -> None:
    report = evaluate_readiness(runtime_config(namespace="production_namespace"))
    assert report.status == "NOT_READY_NAMESPACE"


def test_sidecar_schema_mismatch_blocks_readiness() -> None:
    report = evaluate_readiness(runtime_config(sidecar_schema_version="sidecar.v0"))
    assert report.status == "NOT_READY_SCHEMA"


def test_policy_version_mismatch_is_reported() -> None:
    report = evaluate_readiness(runtime_config(version_policy_version="version-policy.v0"))
    assert report.status == "NOT_READY_POLICY"
    assert "POLICY_VERSION_MISMATCH" in report.reason_codes
