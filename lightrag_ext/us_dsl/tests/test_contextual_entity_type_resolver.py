from __future__ import annotations

from lightrag_ext.us_dsl.contextual_entity_type_resolver import ContextualEntityTypeResolver
from lightrag_ext.us_dsl.entity_type_resolution_types import EntityTypeResolutionContext


def _ctx(**overrides: object) -> EntityTypeResolutionContext:
    data: dict[str, object] = {
        "document_type": "product_design",
        "module_code": "MOD-PRODUCT",
        "primary_domain": "MonitoringReport",
        "feature_key": "FeatureA",
        "source_us_id": "US-25A1",
        "text_unit_id": "tu-1",
        "source_span": {"start": 0, "end": 20},
        "original_entity_name": "对象",
        "original_entity_type": "Misc",
        "evidence_text": "对象有明确的产品设计证据。",
    }
    data.update(overrides)
    return EntityTypeResolutionContext(**data)  # type: ignore[arg-type]


def test_explicit_valid_dsl_type_has_highest_priority() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(section_type="query_section", explicit_dsl_type="FieldSpec", original_entity_type="Location")
    )
    assert decision.resolved_entity_type == "FieldSpec"
    assert decision.decision == "EXPLICIT_ACCEPTED"


def test_confirmed_config_mapping_precedes_heuristic() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(section_type="query_section", confirmed_config_type="FeatureCatalog", original_entity_name="查询列表")
    )
    assert decision.resolved_entity_type == "FeatureCatalog"
    assert decision.decision == "CONFIG_RESOLVED"


def test_structural_context_overrides_generic_location() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(section_type="query_section", original_entity_name="项目列表", original_entity_type="Location")
    )
    assert decision.resolved_entity_type == "ReportSpec"
    assert decision.blocked_from_pfss is False


def test_inquiry_project_list_is_not_location() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(section_type="query_section", original_entity_name="询价项目列表", original_entity_type="Location")
    )
    assert decision.original_entity_type == "Location"
    assert decision.resolved_entity_type == "ReportSpec"


def test_query_list_object_resolves_to_report_spec() -> None:
    decision = ContextualEntityTypeResolver().resolve(_ctx(section_type="list_definition", original_entity_name="项目列表"))
    assert decision.resolved_entity_type == "ReportSpec"


def test_list_column_resolves_to_field_spec() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(section_type="result_grid", relation_role="target", original_entity_name="项目状态列")
    )
    assert decision.resolved_entity_type == "FieldSpec"


def test_task_resolves_to_task_rule() -> None:
    decision = ContextualEntityTypeResolver().resolve(_ctx(primary_domain="Workflow", section_type="task_rule", original_entity_name="待报价确认待办"))
    assert decision.resolved_entity_type == "TaskRule"


def test_handler_resolves_to_role_permission() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(primary_domain="Workflow", relation_type="AssignsHandler", relation_role="target", original_entity_name="Current Handler", original_entity_type="Person")
    )
    assert decision.resolved_entity_type == "RolePermission"


def test_api_resolves_to_integration_endpoint() -> None:
    decision = ContextualEntityTypeResolver().resolve(_ctx(primary_domain="Integration", section_type="api_desc", original_entity_name="报价结果查询 API"))
    assert decision.resolved_entity_type == "IntegrationEndpoint"


def test_migration_rule_resolves_to_data_migration_spec() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(primary_domain="DataMigrationInitialization", section_type="migration_rule", original_entity_name="迁移规则")
    )
    assert decision.resolved_entity_type == "DataMigrationSpec"


def test_generic_location_without_product_context_is_blocked() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(primary_domain=None, feature_key=None, section_type=None, original_entity_name="Paris", original_entity_type="Location", evidence_text="Paris")
    )
    assert decision.decision == "BLOCKED_GENERIC_TYPE"
    assert decision.blocked_from_pfss is True


def test_low_confidence_type_requires_review() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(section_type=None, original_entity_name="查询条件", original_entity_type="Unknown", evidence_text="查询条件")
    )
    assert decision.decision == "CANDIDATE_REVIEW"
    assert decision.requires_review is True
    assert decision.blocked_from_pfss is True


def test_conflicting_high_priority_candidates_are_blocked() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(section_type="query_section", confirmed_config_type="FeatureCatalog|ReportSpec", original_entity_name="查询页面")
    )
    assert decision.decision == "CONFLICT"
    assert decision.blocked_from_pfss is True


def test_resolution_is_deterministic() -> None:
    resolver = ContextualEntityTypeResolver()
    context = _ctx(section_type="query_section", original_entity_name="询价项目列表", original_entity_type="Location")
    assert resolver.resolve(context) == resolver.resolve(context)


def test_original_entity_type_is_preserved() -> None:
    decision = ContextualEntityTypeResolver().resolve(
        _ctx(section_type="query_section", original_entity_name="询价项目列表", original_entity_type="Location")
    )
    assert decision.original_entity_type == "Location"
