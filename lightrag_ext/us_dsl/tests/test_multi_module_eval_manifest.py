from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.multi_module_eval_manifest import validate_manifest_diversity
from lightrag_ext.us_dsl.tests.multi_module_eval_test_helpers import write_manifest_tree


def test_manifest_requires_minimum_module_diversity(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path, module_count=2, include_holdout=True, domains=5)
    report = validate_manifest_diversity(manifest)
    assert report["passed"] is False
    assert "BLOCKED_INSUFFICIENT_MODULE_DIVERSITY" in report["failures"]


def test_manifest_requires_holdout_module(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path, module_count=3, include_holdout=False, domains=5)
    report = validate_manifest_diversity(manifest)
    assert "BLOCKED_MISSING_HOLDOUT_MODULE" in report["failures"]


def test_manifest_requires_domain_coverage(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path, module_count=4, include_holdout=True, domains=2)
    report = validate_manifest_diversity(manifest)
    assert "BLOCKED_INSUFFICIENT_DOMAIN_COVERAGE" in report["failures"]


def test_manifest_has_no_duplicate_module_code(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path, module_count=4, include_holdout=True, domains=5)
    duplicate = list(manifest.modules)
    duplicate[1] = duplicate[0]
    manifest = type(manifest)(manifest.suite_id, manifest.output_dir, manifest.policy, duplicate)
    report = validate_manifest_diversity(manifest)
    assert report["duplicate_module_codes"] == [duplicate[0].module_code]


def test_thresholds_are_policy_driven_not_module_hardcoded(tmp_path: Path) -> None:
    manifest = write_manifest_tree(tmp_path, module_count=4, include_holdout=True, domains=5)
    assert manifest.policy.max_query_p95_latency_ratio == 2.5
    assert manifest.policy.max_per_module_recall_regression == 0.05
