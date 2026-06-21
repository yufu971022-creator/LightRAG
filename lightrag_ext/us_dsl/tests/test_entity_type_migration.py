from __future__ import annotations

import inspect

from lightrag_ext.us_dsl.contextual_entity_type_resolver import ContextualEntityTypeResolver
from lightrag_ext.us_dsl.entity_type_migration import build_type_migration_plan
from lightrag_ext.us_dsl.entity_type_resolution_types import EntityTypeResolutionContext, to_plain_dict
from lightrag_ext.us_dsl.term_normalization_types import TermScope


def _plan(existing_target_identity: bool = True):
    decision = ContextualEntityTypeResolver().resolve(
        EntityTypeResolutionContext(
            document_type="product_design",
            module_code="MOD-PRODUCT",
            primary_domain="MonitoringReport",
            feature_key="InquiryList",
            section_type="query_section",
            original_entity_name="询价项目列表",
            original_entity_type="Location",
            canonical_term="Inquiry Project List",
            source_us_id="US-25A1",
            text_unit_id="tu-1",
            source_span={"start": 0, "end": 10},
            evidence_text="询价项目列表支持按项目状态查询。",
        )
    )
    return build_type_migration_plan(
        original_object={
            "semantic_object_id": "urn:pfss:old:Location:inquiry-project-list",
            "object_type": "Location",
            "canonical_name": "询价项目列表",
            "version_group_key": "vg:old-location",
            "document_version_id": "docver-25a1-v1",
        },
        decision=decision,
        canonical_key="inquiryprojectlist",
        scope=TermScope(module_code="MOD-PRODUCT", domain_code="MonitoringReport", feature_key="InquiryList", object_type=decision.resolved_entity_type),
        relations=[{"relation_id": "rel-old-filter", "src": "urn:pfss:old:Location:inquiry-project-list", "tgt": "urn:pfss:field:project-status", "relation_type": "HasReportFilter"}],
        evidence_mapping_ids=["evidence-25a1-list"],
        existing_target_identity=existing_target_identity,
    )


def test_type_change_changes_semantic_identity() -> None:
    plan = _plan()
    assert plan.old_type == "Location"
    assert plan.new_type == "ReportSpec"
    assert plan.old_semantic_object_id != plan.new_semantic_object_id


def test_type_rekey_plan_updates_relation_endpoints() -> None:
    plan = _plan()
    assert plan.affected_relation_ids == ["rel-old-filter"]
    assert plan.relation_vector_rebuild_required is True


def test_type_rekey_preserves_evidence() -> None:
    plan = _plan()
    assert plan.affected_evidence_mapping_ids == ["evidence-25a1-list"]


def test_existing_target_identity_generates_merge_plan() -> None:
    assert _plan(existing_target_identity=True).merge_target_id is not None
    assert _plan(existing_target_identity=False).merge_target_id is None


def test_version_group_rekeys_with_resolved_type() -> None:
    plan = _plan()
    assert "vg:old-location" in plan.affected_version_group_keys
    assert len(plan.affected_version_group_keys) == 2


def test_production_graph_is_not_rewritten() -> None:
    source = inspect.getsource(build_type_migration_plan)
    assert "Neo4j" not in source
    assert "GraphStorage" not in source
    assert "ainsert" not in source


def test_isolated_migration_is_idempotent() -> None:
    assert to_plain_dict(_plan()) == to_plain_dict(_plan())
