from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EntityAliasRule:
    source_types: tuple[str, ...]
    resolved_type: str
    reason_code: str
    evidence_keywords: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    section_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class BusinessObjectTypeRule:
    source_type_pattern: str
    resolved_type_preferences: tuple[str, ...]
    section_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class RelationMappingRule:
    original_relation: str
    resolved_relation: str
    reason_code: str
    source_must_be_feature: bool = False
    domains: tuple[str, ...] = ()
    evidence_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigRegistry:
    synonym_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    entity_alias_rules: tuple[EntityAliasRule, ...] = field(default_factory=tuple)
    business_object_type_mapping: tuple[BusinessObjectTypeRule, ...] = field(
        default_factory=tuple
    )
    relation_mapping_rules: tuple[RelationMappingRule, ...] = field(default_factory=tuple)
    high_risk_domains: set[str] = field(default_factory=set)
    high_risk_sections: set[str] = field(default_factory=set)
    version_keywords: tuple[str, ...] = ()
    critical_terms: set[str] = field(default_factory=set)
    product_design_markers: tuple[str, ...] = ()
    section_markers: dict[str, tuple[str, ...]] = field(default_factory=dict)


def default_config_registry() -> ConfigRegistry:
    return ConfigRegistry(
        synonym_aliases={},
        entity_alias_rules=(
            EntityAliasRule(
                source_types=("Field", "FieldName", "FieldColumn", "DataField"),
                resolved_type="FieldSpec",
                reason_code="FIELD_TO_FIELDSPEC",
            ),
            EntityAliasRule(
                source_types=("Message", "Prompt", "ErrorMessage"),
                resolved_type="MessageAtom",
                reason_code="MESSAGE_TO_MESSAGE_ATOM",
            ),
            EntityAliasRule(
                source_types=("Audit", "Log", "AuditHistory"),
                resolved_type="AuditLog",
                reason_code="LOG_TO_LOG_ENTITY",
                evidence_keywords=("audit", "history", "审计"),
            ),
            EntityAliasRule(
                source_types=("ReportField", "QueryField", "FilterField"),
                resolved_type="SearchCondition",
                reason_code="REPORT_FIELD_TO_SEARCH_CONDITION",
                domains=("MonitoringReport",),
            ),
            EntityAliasRule(
                source_types=("ReportField", "QueryField", "FilterField"),
                resolved_type="ReportColumn",
                reason_code="REPORT_FIELD_TO_REPORT_COLUMN",
                evidence_keywords=("result", "column", "展示", "结果列"),
            ),
            EntityAliasRule(
                source_types=("Api", "API", "Interface", "Endpoint"),
                resolved_type="BackendApi",
                reason_code="API_TO_INTERFACE_ENTITY",
            ),
            EntityAliasRule(
                source_types=("Config", "Lookup", "Switch"),
                resolved_type="LookupConfig",
                reason_code="LOOKUP_TO_LOOKUP_CONFIG",
                evidence_keywords=("lookup", "值集"),
            ),
            EntityAliasRule(
                source_types=("Config", "Lookup", "Switch"),
                resolved_type="FeatureSwitch",
                reason_code="CONFIG_TO_CONFIG_ENTITY",
            ),
            EntityAliasRule(
                source_types=("Config", "Lookup", "Switch"),
                resolved_type="ConfigItem",
                reason_code="CONFIG_TO_CONFIG_ENTITY",
            ),
        ),
        business_object_type_mapping=(
            BusinessObjectTypeRule(
                source_type_pattern=r".*Deal$",
                resolved_type_preferences=("Deal", "Transaction"),
            ),
            BusinessObjectTypeRule(
                source_type_pattern=r".*(Code|Number)$",
                resolved_type_preferences=("FieldSpec",),
                section_types=("field_table", "report_rule", "api_desc", "migration_rule"),
            ),
        ),
        relation_mapping_rules=(
            RelationMappingRule(
                original_relation="has_child",
                resolved_relation="HasFieldSpec",
                reason_code="HAS_CHILD_FEATURE_FIELD",
                source_must_be_feature=True,
            ),
            RelationMappingRule(
                original_relation="has_child",
                resolved_relation="HasWorkflowNode",
                reason_code="HAS_CHILD_WORKFLOW_NODE",
                evidence_keywords=("workflow", "state", "节点"),
            ),
            RelationMappingRule(
                original_relation="has_child",
                resolved_relation="HasReportColumn",
                reason_code="HAS_CHILD_REPORT_COLUMN",
                domains=("MonitoringReport",),
            ),
            RelationMappingRule(
                original_relation="references_to",
                resolved_relation="UsesMasterData",
                reason_code="REFERENCE_TO_MASTER_DATA",
                evidence_keywords=("master data", "counterparty", "值集", "lookup"),
            ),
            RelationMappingRule(
                original_relation="references_to",
                resolved_relation="HasValueSet",
                reason_code="REFERENCE_TO_VALUE_SET",
                evidence_keywords=("value set", "值集"),
            ),
            RelationMappingRule(
                original_relation="references_to",
                resolved_relation="UsesLookupConfig",
                reason_code="REFERENCE_TO_LOOKUP",
                evidence_keywords=("lookup",),
            ),
            RelationMappingRule(
                original_relation="contains",
                resolved_relation="HasReportColumn",
                reason_code="CONTAINS_TO_SPECIFIC_CONTAINMENT",
            ),
            RelationMappingRule(
                original_relation="contains",
                resolved_relation="HasRuleAtom",
                reason_code="CONTAINS_TO_SPECIFIC_CONTAINMENT",
            ),
        ),
        high_risk_domains={
            "Workflow",
            "Ledger",
            "AccessAudit",
            "Integration",
            "DataMigrationInitialization",
            "RuleManagement",
        },
        high_risk_sections={
            "state_rule",
            "task_rule",
            "api_desc",
            "migration_rule",
            "field_table",
            "dfx_rule",
        },
        version_keywords=(
            "新增",
            "优化",
            "调整",
            "替换",
            "废弃",
            "Removed",
            "Not Involved",
            "旧版本",
            "新版本",
            "回顾",
            "迁移",
        ),
        critical_terms={
            "Swift Code",
            "Bank Internal Code",
            "Deal Number",
            "Instruction Number",
            "Bank Rating",
            "Current Handler",
            "Bank Default Confirmation",
        },
        product_design_markers=(
            "【As】",
            "【I Want】",
            "【Given】",
            "【When】",
            "【Then】",
            "字段",
            "规则",
            "审批",
            "接口",
            "报表",
            "迁移",
        ),
        section_markers={
            "field_table": ("字段", "Field", "是否必填"),
            "state_rule": ("状态", "Approve", "Reject"),
            "task_rule": ("待办", "Task", "Handler"),
            "api_desc": ("接口", "API", "MQ"),
            "migration_rule": ("迁移", "Source", "Target"),
        },
    )


DEFAULT_CONFIG_REGISTRY = default_config_registry()


__all__ = [
    "BusinessObjectTypeRule",
    "ConfigRegistry",
    "DEFAULT_CONFIG_REGISTRY",
    "EntityAliasRule",
    "RelationMappingRule",
    "default_config_registry",
]
