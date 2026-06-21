from __future__ import annotations

from lightrag_ext.us_dsl.contextual_entity_type_resolver import ContextualEntityTypeResolver
from lightrag_ext.us_dsl.entity_type_migration import build_type_migration_plan
from lightrag_ext.us_dsl.entity_type_resolution_policy import EntityTypeResolutionPolicy
from lightrag_ext.us_dsl.entity_type_resolution_types import EntityTypeCandidate, EntityTypeResolutionContext
from lightrag_ext.us_dsl.semantic_identity import build_semantic_identity_key, stable_semantic_object_id, stable_version_group_key
from lightrag_ext.us_dsl.term_normalization_types import TermNormalizationDecision, TermScope


def _ctx(**overrides: object) -> EntityTypeResolutionContext:
    data: dict[str, object] = {
        "document_type": "product_design",
        "module_code": "MOD-GENERAL",
        "primary_domain": "MonitoringReport",
        "feature_key": "GeneralizedFeature",
        "source_us_id": "US-25A1-1",
        "text_unit_id": "tu-generalization",
        "source_span": {"start": 0, "end": 20},
        "original_entity_name": "对象",
        "original_entity_type": "Misc",
        "evidence_text": "对象来自产品设计结构上下文。",
    }
    data.update(overrides)
    return EntityTypeResolutionContext(**data)  # type: ignore[arg-type]


def _resolve(**overrides: object):
    return ContextualEntityTypeResolver().resolve(_ctx(**overrides))


def _term_decision(key: str, scope: TermScope) -> TermNormalizationDecision:
    return TermNormalizationDecision(
        original_term=key,
        lexically_normalized_term=key,
        canonical_term=key,
        canonical_key=key,
        semantic_scope_key=scope.semantic_scope_key(),
        decision="IDENTITY",
        mapping_status=None,
        mapping_source=None,
        confidence=1.0,
    )


def test_monitoring_report_fixture_resolves_by_structure() -> None:
    report = _resolve(original_entity_name="采购申请清单", original_entity_type="Location", section_type="query_section")
    field = _resolve(original_entity_name="审批阶段", relation_type="HasReportFilter", relation_role="target")
    assert report.resolved_entity_type == "ReportSpec"
    assert field.resolved_entity_type == "FieldSpec"


def test_workflow_fixture_resolves_by_structure_and_relation_role() -> None:
    task = _resolve(primary_domain="Workflow", section_type="task_rule", original_entity_name="待复核任务", original_entity_type="Event")
    role = _resolve(primary_domain="Workflow", section_type=None, original_entity_name="当前处理角色", original_entity_type="Person", relation_type="AssignsHandler", relation_role="target")
    assert task.resolved_entity_type == "TaskRule"
    assert role.resolved_entity_type == "RolePermission"
    assert "relation_signature" in role.signals_used


def test_integration_fixture_resolves_without_endpoint_name_hardcode() -> None:
    service = _resolve(primary_domain="Integration", section_type="api_desc", original_entity_name="额度校验服务", original_entity_type="Organization")
    callback = _resolve(primary_domain="Integration", section_type="integration_section", original_entity_name="额度结果回调", original_entity_type="Event")
    assert service.resolved_entity_type == "IntegrationEndpoint"
    assert callback.resolved_entity_type == "IntegrationEndpoint"


def test_migration_fixture_resolves_without_business_name_hardcode() -> None:
    spec = _resolve(primary_domain="DataMigrationInitialization", section_type="migration_rule", original_entity_name="历史合同数据迁移", original_entity_type="Event")
    field = _resolve(primary_domain="DataMigrationInitialization", section_type=None, original_entity_name="字段映射", relation_type="HasFieldSpec", relation_role="target")
    assert spec.resolved_entity_type == "DataMigrationSpec"
    assert field.resolved_entity_type == "FieldSpec"


def test_access_audit_fixture_resolves_without_role_name_hardcode() -> None:
    role = _resolve(primary_domain="AccessAudit", section_type=None, original_entity_name="结算管理员", original_entity_type="Person", relation_type="AssignsHandler", relation_role="target")
    rule = _resolve(primary_domain="AccessAudit", section_type="access_audit", original_entity_name="审计记录规则", original_entity_type="Event")
    assert role.resolved_entity_type == "RolePermission"
    assert rule.resolved_entity_type == "RuleAtom"


def test_master_data_fixture_resolves_without_object_name_hardcode() -> None:
    obj = _resolve(primary_domain="MasterData", section_type="master_data", original_entity_name="客户主数据", original_entity_type="Organization")
    field = _resolve(primary_domain="MasterData", section_type=None, original_entity_name="客户编码", relation_type="HasFieldSpec", relation_role="target")
    assert obj.resolved_entity_type == "DomainObject"
    assert field.resolved_entity_type == "FieldSpec"


def test_unknown_module_name_resolves_from_context() -> None:
    decision = _resolve(original_entity_name="Zeta 方案清单", original_entity_type="Location", section_type="query_section")
    assert decision.resolved_entity_type == "ReportSpec"
    assert "section_type" in decision.signals_used


def test_generic_location_without_context_is_blocked() -> None:
    decision = _resolve(primary_domain=None, feature_key=None, text_unit_id="tu", section_type=None, original_entity_name="Berlin", original_entity_type="Location", evidence_text="Berlin")
    assert decision.decision == "BLOCKED_GENERIC_TYPE"
    assert decision.blocked_from_pfss is True


def test_ambiguous_short_name_requires_review() -> None:
    decision = _resolve(primary_domain=None, feature_key=None, text_unit_id="tu", section_type=None, original_entity_name="结果", original_entity_type="Misc", evidence_text="结果")
    assert decision.blocked_from_pfss is True
    assert decision.decision in {"NO_SAFE_TYPE", "CANDIDATE_REVIEW", "BLOCKED_GENERIC_TYPE"}


def test_resolution_reports_signals_used() -> None:
    decision = _resolve(original_entity_name="Zeta 方案清单", original_entity_type="Location", section_type="query_section")
    assert decision.selected_type == "ReportSpec"
    assert decision.signals_used
    assert decision.reason_codes


def test_generic_ner_only_signal_cannot_auto_accept() -> None:
    decision = EntityTypeResolutionPolicy().decide(
        original_entity_type="Location",
        candidates=[EntityTypeCandidate("Location", 0.99, "GENERIC_NER", ["generic_ner_weak_hint"], {})],
        evidence_complete=True,
    )
    assert decision.blocked_from_pfss is True


def test_name_keyword_only_signal_cannot_auto_accept() -> None:
    decision = _resolve(primary_domain=None, feature_key=None, section_type=None, original_entity_name="查询条件", original_entity_type="Unknown", evidence_text="查询条件")
    assert decision.decision == "CANDIDATE_REVIEW"
    assert decision.blocked_from_pfss is True


def test_confidence_and_reason_codes_are_deterministic() -> None:
    context = _ctx(original_entity_name="Zeta 方案清单", original_entity_type="Location", section_type="query_section")
    resolver = ContextualEntityTypeResolver()
    first = resolver.resolve(context)
    second = resolver.resolve(context)
    assert first.confidence == second.confidence
    assert first.reason_codes == second.reason_codes
    assert first.signals_used == second.signals_used


def test_generalization_does_not_break_term_normalization_identity() -> None:
    scope = TermScope(module_code="MOD-GENERAL", domain_code="MonitoringReport", feature_key="ZetaFeature", object_type="ReportSpec")
    identity = build_semantic_identity_key(_term_decision("zetalist", scope), scope=scope, object_type="ReportSpec")
    assert identity.canonical_object_key == "zetalist"
    assert stable_semantic_object_id(identity).startswith("urn:pfss:")


def test_same_resolved_type_keeps_stable_identity() -> None:
    scope = TermScope(module_code="MOD-GENERAL", domain_code="MonitoringReport", feature_key="ZetaFeature", object_type="ReportSpec")
    first = build_semantic_identity_key(_term_decision("zetalist", scope), scope=scope, object_type="ReportSpec")
    second = build_semantic_identity_key(_term_decision("zetalist", scope), scope=scope, object_type="ReportSpec")
    assert stable_semantic_object_id(first) == stable_semantic_object_id(second)
    assert stable_version_group_key(first) == stable_version_group_key(second)


def test_type_change_generates_rekey_plan_not_direct_rewrite() -> None:
    decision = _resolve(original_entity_name="Zeta 方案清单", original_entity_type="Location", section_type="query_section")
    scope = TermScope(module_code="MOD-GENERAL", domain_code="MonitoringReport", feature_key="ZetaFeature", object_type=decision.resolved_entity_type)
    plan = build_type_migration_plan(
        original_object={"semantic_object_id": "urn:pfss:old:Location:zeta-list", "object_type": "Location", "canonical_name": "Zeta 方案清单", "version_group_key": "vg:old", "document_version_id": "docver-generalization"},
        decision=decision,
        canonical_key="zetalist",
        scope=scope,
        relations=[{"relation_id": "rel-zeta-filter", "src": "urn:pfss:old:Location:zeta-list", "tgt": "urn:pfss:field:stage", "relation_type": "HasReportFilter"}],
        evidence_mapping_ids=["evidence-zeta"],
    )
    assert plan.old_semantic_object_id != plan.new_semantic_object_id
    assert plan.pfss_delete_plan
    assert plan.affected_evidence_mapping_ids == ["evidence-zeta"]


def test_uncertain_type_does_not_pollute_pfss_identity() -> None:
    decision = _resolve(primary_domain=None, feature_key=None, section_type=None, original_entity_name="结果", original_entity_type="Misc", evidence_text="结果")
    assert decision.blocked_from_pfss is True
    assert decision.resolved_entity_type is None
