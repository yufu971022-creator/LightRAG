from __future__ import annotations

from lightrag_ext.us_dsl.scoped_term_resolver import resolve_term
from lightrag_ext.us_dsl.semantic_identity import build_semantic_identity_key, stable_semantic_object_id, stable_semantic_relation_id, stable_version_group_key
from lightrag_ext.us_dsl.term_normalization_types import TermScope
from lightrag_ext.us_dsl.term_registry_importer import import_term_registry_csv, write_fixture_registry_csv


def _registry(tmp_path):
    return import_term_registry_csv(write_fixture_registry_csv(tmp_path / "registry.csv"))


def _id(term: str, scope: TermScope, registry, object_type: str = "FieldSpec") -> str:
    decision = resolve_term(term, scope=scope, registry=registry)
    return stable_semantic_object_id(build_semantic_identity_key(decision, scope=scope, object_type=object_type))


def test_aliases_share_stable_semantic_object_id(tmp_path):
    registry = _registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Integration", feature_key="PaymentFeature", object_type="FieldSpec")
    assert _id("SWIFTCODE", scope, registry) == _id("SWIFT CODE", scope, registry)


def test_identity_is_stable_across_documents(tmp_path):
    registry = _registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission")
    assert _id("Current Handler", scope, registry, "RolePermission") == _id("当前处理人", scope, registry, "RolePermission")


def test_identity_is_stable_across_document_versions(tmp_path):
    registry = _registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission")
    v1_id = _id("Current Handler", scope, registry, "RolePermission")
    v2_id = _id("当前处理人", scope, registry, "RolePermission")
    assert v1_id == v2_id


def test_domain_feature_object_type_affect_identity(tmp_path):
    registry = _registry(tmp_path)
    bank = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec")
    approval = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="ApprovalFeature", object_type="FieldSpec")
    assert _id("Bank Status", bank, registry) != _id("Approval Status", approval, registry)


def test_original_language_does_not_affect_identity(tmp_path):
    registry = _registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission")
    assert _id("Current Handler", scope, registry, "RolePermission") == _id("当前处理人", scope, registry, "RolePermission")


def test_relation_id_uses_stable_endpoint_ids(tmp_path):
    registry = _registry(tmp_path)
    handler_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission")
    swift_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Integration", feature_key="PaymentFeature", object_type="FieldSpec")
    src = _id("当前处理人", handler_scope, registry, "RolePermission")
    tgt = _id("SWIFTCODE", swift_scope, registry)
    rel = stable_semantic_relation_id(src_semantic_object_id=src, relation_type="RequiresPermission", tgt_semantic_object_id=tgt)
    assert src in rel and tgt in rel


def test_version_group_uses_canonical_identity(tmp_path):
    registry = _registry(tmp_path)
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec")
    bank = build_semantic_identity_key(resolve_term("Bank Status", scope=scope, registry=registry), scope=scope, object_type="FieldSpec")
    zh = build_semantic_identity_key(resolve_term("银行状态", scope=scope, registry=registry), scope=scope, object_type="FieldSpec")
    assert stable_version_group_key(bank) == stable_version_group_key(zh)


def test_distinct_status_objects_have_distinct_version_groups(tmp_path):
    registry = _registry(tmp_path)
    bank_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec")
    approval_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="ApprovalFeature", object_type="FieldSpec")
    bank = stable_version_group_key(build_semantic_identity_key(resolve_term("Bank Status", scope=bank_scope, registry=registry), scope=bank_scope, object_type="FieldSpec"))
    approval = stable_version_group_key(build_semantic_identity_key(resolve_term("Approval Status", scope=approval_scope, registry=registry), scope=approval_scope, object_type="FieldSpec"))
    assert bank != approval
