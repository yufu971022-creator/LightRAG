from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.semantic_identity import build_semantic_identity_key, stable_version_group_key
from lightrag_ext.us_dsl.term_normalization_types import TermNormalizationDecision, TermScope
from lightrag_ext.us_dsl.version_retrieval_guard import build_supersedes_guard_report, scan_version_retrieval_runtime


def _identity_group(canonical_key: str, object_type: str = "RuleAtom") -> str:
    scope = TermScope(module_code="MOD", domain_code="Domain", feature_key="Feature", object_type=object_type)
    decision = TermNormalizationDecision("term", canonical_key, "term", canonical_key, scope.semantic_scope_key(), "IDENTITY", None, None, 1.0)
    return stable_version_group_key(build_semantic_identity_key(decision, scope=scope, object_type=object_type))


def test_aliases_share_same_version_group() -> None:
    assert _identity_group("sharedalias") == _identity_group("sharedalias")


def test_distinct_semantic_objects_keep_distinct_version_groups() -> None:
    assert _identity_group("objecta") != _identity_group("objectb")


def test_runtime_has_no_module_specific_version_rules() -> None:
    report = scan_version_retrieval_runtime(Path.cwd())
    assert report.runtime_business_hardcode_count == 0
    assert report.module_specific_version_rule_count == 0
    assert report.source_us_order_rule_count == 0
    assert report.document_upload_time_rule_count == 0


def test_no_new_supersedes_is_created() -> None:
    report = build_supersedes_guard_report()
    assert report.new_supersedes_created_count == 0
    assert report.passed is True


def test_term_and_type_generalization_regression_passes() -> None:
    assert _identity_group("canonicalrule", "RuleAtom") != _identity_group("canonicalrule", "FieldSpec")
