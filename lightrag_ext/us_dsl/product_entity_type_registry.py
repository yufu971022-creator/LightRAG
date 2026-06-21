from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PFSS_ENTITY_TYPES = {
    "SourceDocument",
    "UserStory",
    "FeatureCatalog",
    "DomainObject",
    "FieldSpec",
    "RuleAtom",
    "TaskRule",
    "StateTransition",
    "MessageAtom",
    "RolePermission",
    "IntegrationEndpoint",
    "ReportSpec",
    "DataMigrationSpec",
    "RuleVersion",
    "CanonicalTerm",
    "EvidenceSpan",
}


@dataclass(frozen=True)
class ProductEntityTypeDefinition:
    type_code: str
    display_name: str
    allowed_domains: set[str] = field(default_factory=set)
    preferred_section_types: set[str] = field(default_factory=set)
    lexical_cues: set[str] = field(default_factory=set)
    structural_cues: set[str] = field(default_factory=set)
    allowed_relation_roles: set[str] = field(default_factory=set)
    high_risk: bool = False
    requires_evidence: bool = True


class ProductEntityTypeRegistry:
    def __init__(self, definitions: dict[str, ProductEntityTypeDefinition] | None = None) -> None:
        self._definitions = definitions or _default_definitions()

    def contains(self, type_code: str | None) -> bool:
        return bool(type_code and type_code in self._definitions)

    def get(self, type_code: str) -> ProductEntityTypeDefinition:
        return self._definitions[type_code]

    def all_types(self) -> set[str]:
        return set(self._definitions)

    def is_domain_allowed(self, type_code: str, domain_code: str | None) -> bool:
        definition = self.get(type_code)
        return not definition.allowed_domains or not domain_code or domain_code in definition.allowed_domains

    def to_report(self) -> dict[str, Any]:
        return {key: _definition_dict(value) for key, value in sorted(self._definitions.items())}


def default_product_entity_type_registry() -> ProductEntityTypeRegistry:
    return ProductEntityTypeRegistry()


def _default_definitions() -> dict[str, ProductEntityTypeDefinition]:
    rows = [
        ProductEntityTypeDefinition("SourceDocument", "Source Document", structural_cues={"document"}),
        ProductEntityTypeDefinition("UserStory", "User Story", preferred_section_types={"user_story"}),
        ProductEntityTypeDefinition("FeatureCatalog", "Feature Catalog", lexical_cues={"页面", "菜单", "功能", "入口", "模块", "能力", "page", "menu", "feature"}, structural_cues={"page_title", "menu_entry", "feature_entry"}),
        ProductEntityTypeDefinition("DomainObject", "Domain Object", lexical_cues={"对象", "主数据", "domain", "object"}),
        ProductEntityTypeDefinition("FieldSpec", "Field Spec", preferred_section_types={"field_table", "query_condition", "result_column"}, lexical_cues={"字段", "列", "查询条件", "输入项", "展示项", "field", "column"}, structural_cues={"table_column", "field_row", "query_condition"}),
        ProductEntityTypeDefinition("RuleAtom", "Rule Atom", preferred_section_types={"business_rule", "dfx_rule"}, lexical_cues={"规则", "校验", "控制", "rule"}),
        ProductEntityTypeDefinition("TaskRule", "Task Rule", preferred_section_types={"task_rule"}, lexical_cues={"待办", "任务", "处理动作", "转审", "关闭", "task", "todo"}),
        ProductEntityTypeDefinition("StateTransition", "State Transition", preferred_section_types={"state_rule"}, lexical_cues={"状态流转", "状态迁移", "transition"}),
        ProductEntityTypeDefinition("MessageAtom", "Message Atom", preferred_section_types={"message_rule"}, lexical_cues={"消息", "提示", "通知", "message"}),
        ProductEntityTypeDefinition("RolePermission", "Role Permission", lexical_cues={"角色", "权限", "处理人", "handler", "permission", "role"}),
        ProductEntityTypeDefinition("IntegrationEndpoint", "Integration Endpoint", preferred_section_types={"api_desc", "integration_section"}, lexical_cues={"api", "mq", "接口", "服务端点", "回调", "endpoint", "callback"}),
        ProductEntityTypeDefinition("ReportSpec", "Report Spec", preferred_section_types={"report_rule", "query_section", "list_definition", "result_grid", "export_section"}, lexical_cues={"查询", "列表", "报表", "结果集", "导出", "search", "list", "report"}, structural_cues={"query_page", "list_definition", "result_grid", "export_section"}),
        ProductEntityTypeDefinition("DataMigrationSpec", "Data Migration Spec", preferred_section_types={"migration_rule", "migration_section"}, lexical_cues={"迁移", "初始化", "dry-run", "字段校验", "migration", "initialization"}),
        ProductEntityTypeDefinition("RuleVersion", "Rule Version", lexical_cues={"版本", "version"}, high_risk=True),
        ProductEntityTypeDefinition("CanonicalTerm", "Canonical Term", lexical_cues={"术语", "term"}),
        ProductEntityTypeDefinition("EvidenceSpan", "Evidence Span", structural_cues={"evidence"}),
    ]
    return {row.type_code: row for row in rows}


def _definition_dict(value: ProductEntityTypeDefinition) -> dict[str, Any]:
    return {
        "type_code": value.type_code,
        "display_name": value.display_name,
        "allowed_domains": sorted(value.allowed_domains),
        "preferred_section_types": sorted(value.preferred_section_types),
        "lexical_cues": sorted(value.lexical_cues),
        "structural_cues": sorted(value.structural_cues),
        "allowed_relation_roles": sorted(value.allowed_relation_roles),
        "high_risk": value.high_risk,
        "requires_evidence": value.requires_evidence,
    }
