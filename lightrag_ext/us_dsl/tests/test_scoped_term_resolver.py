from __future__ import annotations

from lightrag_ext.us_dsl.scoped_term_resolver import resolve_term
from lightrag_ext.us_dsl.term_normalization_types import TermMappingRecord, TermScope
from lightrag_ext.us_dsl.term_registry import TermRegistry
from lightrag_ext.us_dsl.term_registry_importer import import_term_registry_csv, write_fixture_registry_csv


def _registry(tmp_path):
    return import_term_registry_csv(write_fixture_registry_csv(tmp_path / "registry.csv"))


def _conflict_registry():
    registry = TermRegistry(allow_conflicts=True)
    scope = TermScope(module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="ConflictFeature", object_type="FieldSpec", language_code="en")
    registry.add(TermMappingRecord("a", "Status", "Bank Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True))
    registry.add(TermMappingRecord("b", "Status", "Approval Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True))
    return registry


def test_swift_code_variants_normalize_to_one_canonical_term(tmp_path):
    registry = _registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Integration", feature_key="PaymentFeature", object_type="FieldSpec")
    assert {resolve_term(term, scope=scope, registry=registry).canonical_key for term in ["SWIFTCODE", "SWIFT CODE", "swift-code", "swift_code"]} == {"swiftcode"}


def test_confirmed_bilingual_alias_normalizes_in_scope(tmp_path):
    registry = _registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission")
    assert resolve_term("当前处理人", scope=scope, registry=registry).canonical_term == "Current Handler"


def test_unscoped_generic_status_does_not_auto_merge(tmp_path):
    decision = resolve_term("Status", scope=TermScope(), registry=_registry(tmp_path))
    assert decision.decision == "NO_MAPPING"


def test_scoped_status_mapping_can_resolve(tmp_path):
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec")
    decision = resolve_term("状态", scope=scope, registry=_registry(tmp_path))
    assert decision.canonical_term == "Bank Status"
    assert decision.requires_review is False


def test_bank_approval_task_status_remain_distinct(tmp_path):
    registry = _registry(tmp_path)
    scopes = [
        TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec"),
        TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="ApprovalFeature", object_type="FieldSpec"),
        TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="TaskFeature", object_type="FieldSpec"),
    ]
    terms = ["Bank Status", "Approval Status", "Task Status"]
    assert len({resolve_term(term, scope=scope, registry=registry).canonical_key for term, scope in zip(terms, scopes, strict=True)}) == 3


def test_search_translation_requires_confirmed_scope(tmp_path):
    registry = _registry(tmp_path)
    assert resolve_term("查询", scope=TermScope(), registry=registry).decision == "NO_MAPPING"
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="MonitoringReport", feature_key="MonitoringSearch", object_type="ReportSpec")
    assert resolve_term("查询", scope=scope, registry=registry).canonical_term == "Search"


def test_conflicting_mapping_returns_term_ambiguity():
    scope = TermScope(module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="ConflictFeature", object_type="FieldSpec")
    decision = resolve_term("Status", scope=scope, registry=_conflict_registry())
    assert decision.decision == "CONFLICT"
    assert decision.requires_review is True


def test_low_confidence_result_requires_review(tmp_path):
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="CandidateFeature", object_type="FieldSpec")
    decision = resolve_term("Handler", scope=scope, registry=_registry(tmp_path))
    assert decision.decision == "CANDIDATE_REVIEW"


def test_resolution_is_deterministic(tmp_path):
    registry = _registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Integration", feature_key="PaymentFeature", object_type="FieldSpec")
    assert resolve_term("SWIFTCODE", scope=scope, registry=registry) == resolve_term("SWIFTCODE", scope=scope, registry=registry)
