from __future__ import annotations

from lightrag_ext.us_dsl.term_normalization_migration import build_term_normalization_migration_plan
from lightrag_ext.us_dsl.term_normalization_types import TermMappingRecord, TermScope
from lightrag_ext.us_dsl.term_registry import TermRegistry
from lightrag_ext.us_dsl.term_registry_importer import import_term_registry_csv, write_fixture_registry_csv


def _registry(tmp_path):
    return import_term_registry_csv(write_fixture_registry_csv(tmp_path / "registry.csv"))


def _object(object_id: str, name: str, domain: str, feature: str, object_type: str = "FieldSpec") -> dict[str, str]:
    return {"semantic_object_id": object_id, "canonical_name": name, "system_name": "CoreSystem", "module_code": "MOD-PRODUCT", "domain_code": domain, "feature_key": feature, "object_type": object_type, "version_group_key": f"vg:{name}"}


def test_confirmed_duplicate_nodes_generate_merge_plan(tmp_path):
    plan = build_term_normalization_migration_plan([
        _object("old:swiftcode", "SWIFTCODE", "Integration", "PaymentFeature"),
        _object("old:swift-code", "SWIFT CODE", "Integration", "PaymentFeature"),
    ], registry=_registry(tmp_path))
    assert len(plan.confirmed_merge_groups) == 1


def test_candidate_alias_generates_no_merge_plan(tmp_path):
    plan = build_term_normalization_migration_plan([_object("old:candidate", "Handler", "Workflow", "CandidateFeature")], registry=_registry(tmp_path))
    assert plan.confirmed_merge_groups == []
    assert plan.merge_candidate_groups == [["old:candidate"]]


def test_conflict_generates_review_issue():
    registry = TermRegistry(allow_conflicts=True)
    scope = TermScope(module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="ConflictFeature", object_type="FieldSpec", language_code="en")
    registry.add(TermMappingRecord("a", "Status", "Bank Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True))
    registry.add(TermMappingRecord("b", "Status", "Approval Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True))
    plan = build_term_normalization_migration_plan([_object("old:conflict", "Status", "Ledger", "ConflictFeature")], registry=registry)
    assert plan.conflict_groups == [["old:conflict"]]
    assert plan.planned_actions[0]["action"] == "TERM_AMBIGUITY_REVIEW"


def test_mapping_change_marks_rebuild_required(tmp_path):
    plan = build_term_normalization_migration_plan([_object("old:swiftcode", "SWIFTCODE", "Integration", "PaymentFeature")], registry=_registry(tmp_path))
    assert plan.graph_rebuild_required_count == 1
