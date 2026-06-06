from __future__ import annotations

from typing import Any

from .impact_analysis_types import ImpactAnalysisCase


LC_IMPACT_CASES = (
    ImpactAnalysisCase(
        case_id="LC-IMPACT-001-bank-status",
        module_name="LC",
        case_pack_name="LC_IMPACT_ANALYSIS",
        level="L2",
        change_request="如果 Bank Status 的取值或含义调整，需要分析会影响哪些查询、台账、状态和迁移能力。",
        impact_task_type="FIELD_STATUS_IMPACT",
        expected_impact_dimensions=["Ledger", "MonitoringReport", "DataMigrationInitialization"],
        expected_entities=["Bank Status", "Removed", "Not Involved", "Historical Data Migration"],
        expected_relations=["HasReportFilter", "HasStateTransition", "MapsSourceToTarget"],
        expected_domains=["MonitoringReport", "DataMigrationInitialization"],
        expected_sections=["field_table", "report_rule", "migration_rule"],
        expected_evidence_keywords=["Bank Status", "Removed", "Not Involved", "Swift Code"],
        forbidden_claims=["所有模块都会失败", "自动触发清算"],
        must_not_do=["不得把可能影响写成确定事实。"],
        grading_notes="应通过图谱路径覆盖台账、查询状态和迁移相关影响，并区分证据支持与待确认。",
        graph_coverage_expectation="full",
    ),
    ImpactAnalysisCase(
        case_id="LC-IMPACT-002-transfer-to",
        module_name="LC",
        case_pack_name="LC_IMPACT_ANALYSIS",
        level="L2",
        change_request="如果 Transfer To 转审规则变化，需要分析对 Current Handler、待办维护权限和 Bank Default Confirmation 的影响。",
        impact_task_type="WORKFLOW_PERMISSION_IMPACT",
        expected_impact_dimensions=["Workflow", "AccessAudit"],
        expected_entities=["Transfer To", "Current Handler", "Bank Default Confirmation"],
        expected_relations=["TransfersTask", "HasPermission"],
        expected_domains=["Workflow", "AccessAudit"],
        expected_sections=["task_rule", "field_table"],
        expected_evidence_keywords=["Transfer To", "Current Handler", "Bank Default Confirmation"],
        forbidden_claims=["自动通过审批", "所有用户可维护"],
        must_not_do=["不得编造审批流或完整权限矩阵。"],
        grading_notes="应说明转审路径、处理人和权限影响。",
        graph_coverage_expectation="full",
    ),
    ImpactAnalysisCase(
        case_id="LC-IMPACT-003-risk-api",
        module_name="LC",
        case_pack_name="LC_IMPACT_ANALYSIS",
        level="L1",
        change_request="如果外部风险认证接口字段变化，需要分析 eflowNum 和 Suggested Rating 对流程和字段映射的影响。",
        impact_task_type="INTEGRATION_FIELD_IMPACT",
        expected_impact_dimensions=["Integration", "Workflow"],
        expected_entities=["Risk Certification API", "eflowNum", "Suggested Rating"],
        expected_relations=["CallsBackendApi"],
        expected_domains=["Integration"],
        expected_sections=["api_desc"],
        expected_evidence_keywords=["eflowNum", "Suggested Rating"],
        forbidden_claims=["固定接口 URL", "固定外部系统名"],
        must_not_do=["不得编造接口 URL 或外部系统名。"],
        grading_notes="应覆盖接口字段作用和流程影响边界。",
        graph_coverage_expectation="full",
    ),
    ImpactAnalysisCase(
        case_id="LC-IMPACT-004-swift-code",
        module_name="LC",
        case_pack_name="LC_IMPACT_ANALYSIS",
        level="L2",
        change_request="如果 Swift Code 的维护规则变化，需要分析 Bank Internal Code、回顾电子流和历史迁移的影响。",
        impact_task_type="MASTER_DATA_MIGRATION_IMPACT",
        expected_impact_dimensions=["MasterData", "Workflow", "DataMigrationInitialization"],
        expected_entities=["Swift Code", "Bank Internal Code", "Historical Data Migration"],
        expected_relations=["DependsOn", "MapsSourceToTarget"],
        expected_domains=["MasterData", "DataMigrationInitialization"],
        expected_sections=["field_table", "migration_rule"],
        expected_evidence_keywords=["Swift Code", "Bank Internal Code", "dry-run"],
        forbidden_claims=["自动修复所有历史数据"],
        must_not_do=["不得混淆 Swift Code 和 Bank Internal Code。"],
        grading_notes="应覆盖主数据字段、回顾电子流和迁移风险。",
        graph_coverage_expectation="full",
    ),
    ImpactAnalysisCase(
        case_id="LC-IMPACT-005-access-audit",
        module_name="LC",
        case_pack_name="LC_IMPACT_ANALYSIS",
        level="L1",
        change_request="如果可接受银行维护权限变化，需要分析 Data Scope、AuditLog 和 OperationLog 的影响。",
        impact_task_type="ACCESS_AUDIT_IMPACT",
        expected_impact_dimensions=["AccessAudit"],
        expected_entities=["Acceptable Bank Audit Log", "OperationLog", "Data Scope"],
        expected_relations=["WritesOperationLog", "HasPermission"],
        expected_domains=["AccessAudit"],
        expected_sections=["task_rule", "field_table"],
        expected_evidence_keywords=["AuditLog", "OperationLog", "Data Scope"],
        forbidden_claims=["完整权限矩阵", "所有角色列表"],
        must_not_do=["不得编造完整权限矩阵。"],
        grading_notes="应覆盖权限和审计记录影响，并明确证据不足项。",
        graph_coverage_expectation="full",
    ),
    ImpactAnalysisCase(
        case_id="LC-IMPACT-006-version",
        module_name="LC",
        case_pack_name="LC_IMPACT_ANALYSIS",
        level="L2",
        change_request="如果历史 US 和后续 US 对同一规则不一致，需要分析版本不确定对影响分析结论的风险。",
        impact_task_type="VERSION_IMPACT",
        expected_impact_dimensions=["RuleManagement"],
        expected_entities=[],
        expected_relations=["HasVersion", "VersionReviewRequired"],
        expected_domains=[],
        expected_sections=["business_rule", "dfx_rule"],
        expected_evidence_keywords=["latestFlag", "versionStatus", "supersedes"],
        forbidden_claims=["无条件以后出现的 US 为准"],
        must_not_do=["不得硬判最新规则。"],
        grading_notes="应使用版本 review signal 输出待确认，不得伪造 Supersedes。",
        graph_coverage_expectation="full",
    ),
)


def default_lc_impact_analysis_cases() -> list[ImpactAnalysisCase]:
    return list(LC_IMPACT_CASES)


def serialize_lc_impact_analysis_case(case: ImpactAnalysisCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "module_name": case.module_name,
        "case_pack_name": case.case_pack_name,
        "level": case.level,
        "change_request": case.change_request,
        "impact_task_type": case.impact_task_type,
        "expected_impact_dimensions": list(case.expected_impact_dimensions),
        "expected_entities": list(case.expected_entities),
        "expected_relations": list(case.expected_relations),
    }


__all__ = [
    "LC_IMPACT_CASES",
    "default_lc_impact_analysis_cases",
    "serialize_lc_impact_analysis_case",
]
