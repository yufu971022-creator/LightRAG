from __future__ import annotations

from lightrag_ext.us_dsl.tests.version_retrieval_test_helpers import service
from lightrag_ext.us_dsl.version_context_builder import VersionContextBuilder
from lightrag_ext.us_dsl.version_retrieval_types import VersionQueryRequest


def _context(group: str, intent: str, query: str = "query"):
    result = service().retrieve(VersionQueryRequest(query, explicit_intent=intent, version_group_key=group))
    return VersionContextBuilder().build(result)


def test_confirmed_current_context_is_safe_for_deterministic_answer() -> None:
    context = _context("vg:unique-current", "CURRENT")
    assert context.safe_for_deterministic_answer is True
    assert "当前规则已确认" in context.current_summary


def test_unconfirmed_context_requires_warning() -> None:
    context = _context("vg:weak-change", "CURRENT")
    assert context.safe_for_deterministic_answer is False
    assert context.version_warnings


def test_compare_context_contains_version_differences() -> None:
    context = _context("vg:supersedes", "COMPARE")
    assert "版本对比包含" in context.comparison_summary


def test_migration_context_contains_old_and_new_rules() -> None:
    context = _context("vg:issue", "MIGRATION")
    assert "旧规则" in context.recommended_answer_behavior or "新规则" in context.recommended_answer_behavior


def test_context_contains_evidence_references() -> None:
    context = _context("vg:unique-current", "CURRENT")
    assert context.selected_evidence
    assert context.selected_evidence[0]["text_unit_id"]


def test_internal_policy_codes_are_not_exposed_as_business_answer() -> None:
    context = _context("vg:issue", "CURRENT")
    text = " ".join([context.current_summary, context.historical_summary, context.comparison_summary, context.uncertainty_summary, context.recommended_answer_behavior])
    assert "VERSION_REVIEW_REQUIRED_BLOCKED" not in text
    assert "policy score" not in text
