from __future__ import annotations

from lightrag_ext.us_dsl.term_query_expander import expand_query_terms
from lightrag_ext.us_dsl.term_registry_importer import import_term_registry_csv, write_fixture_registry_csv


def _registry(tmp_path):
    return import_term_registry_csv(write_fixture_registry_csv(tmp_path / "registry.csv"))


def test_query_expansion_returns_confirmed_aliases(tmp_path):
    result = expand_query_terms(["Current Handler"], module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission", registry=_registry(tmp_path))
    assert "当前处理人" in result.confirmed_aliases


def test_query_expansion_excludes_rejected_aliases(tmp_path):
    result = expand_query_terms(["Owner"], module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="RejectedFeature", object_type="FieldSpec", registry=_registry(tmp_path))
    assert "Owner" not in result.confirmed_aliases
    assert "Owner" in result.rejected_aliases


def test_query_expansion_keeps_candidate_separate(tmp_path):
    result = expand_query_terms(["Handler"], module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="CandidateFeature", object_type="FieldSpec", registry=_registry(tmp_path))
    assert "Handler" in result.candidate_aliases
    assert "Handler" not in result.confirmed_aliases


def test_query_expansion_respects_scope(tmp_path):
    registry = _registry(tmp_path)
    scoped = expand_query_terms(["查询"], module_code="MOD-PRODUCT", domain_code="MonitoringReport", feature_key="MonitoringSearch", object_type="ReportSpec", registry=registry)
    unscoped = expand_query_terms(["查询"], registry=registry)
    assert "Search" in scoped.canonical_terms
    assert "Search" not in unscoped.canonical_terms


def test_query_expansion_is_not_connected_to_live_query(tmp_path):
    result = expand_query_terms(["Current Handler"], module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission", registry=_registry(tmp_path))
    assert result.live_query_connected is False
