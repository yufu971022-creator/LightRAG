from __future__ import annotations

import pytest

from lightrag_ext.us_dsl.scoped_term_resolver import resolve_term
from lightrag_ext.us_dsl.term_normalization_types import TermMappingRecord, TermScope
from lightrag_ext.us_dsl.term_registry import TermRegistry, TermRegistryConflictError
from lightrag_ext.us_dsl.term_registry_importer import import_term_registry_csv, write_fixture_registry_csv


def _fixture_registry(tmp_path):
    path = write_fixture_registry_csv(tmp_path / "registry.csv")
    return import_term_registry_csv(path)


def test_csv_registry_import(tmp_path):
    registry = _fixture_registry(tmp_path)
    assert len(registry.records()) >= 10


def test_registry_rejects_conflicting_confirmed_mapping_in_same_scope():
    scope = TermScope(module_code="M", domain_code="Ledger", feature_key="F", object_type="FieldSpec", language_code="en")
    registry = TermRegistry()
    registry.add(TermMappingRecord("a", "Status", "Bank Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True))
    with pytest.raises(TermRegistryConflictError):
        registry.add(TermMappingRecord("b", "Status", "Approval Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True))


def test_more_specific_scope_wins():
    registry = TermRegistry()
    registry.add(TermMappingRecord("global", "Status", "Generic Status", "en", "en", "BUSINESS_ALIAS", TermScope(object_type="FieldSpec", language_code="en"), 1.0, "CONFIRMED", "CONFIG", False))
    scope = TermScope(module_code="M", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec", language_code="en")
    registry.add(TermMappingRecord("specific", "Status", "Bank Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True))
    decision = resolve_term("Status", scope=scope, registry=registry)
    assert decision.canonical_term == "Bank Status"


def test_candidate_mapping_does_not_auto_confirm(tmp_path):
    registry = _fixture_registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="CandidateFeature", object_type="FieldSpec")
    decision = resolve_term("Handler", scope=scope, registry=registry)
    assert decision.decision == "CANDIDATE_REVIEW"
    assert decision.requires_review is True


def test_rejected_mapping_is_never_used(tmp_path):
    registry = _fixture_registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="RejectedFeature", object_type="FieldSpec")
    decision = resolve_term("Owner", scope=scope, registry=registry)
    assert decision.decision == "REJECTED_MAPPING"
    assert decision.canonical_term == "Owner"


def test_registry_version_is_reported(tmp_path):
    registry = _fixture_registry(tmp_path)
    report = registry.validation_report()
    assert report["registry_version"] == "25A-0"
