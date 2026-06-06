from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TOP_LEVEL_ENTITY_TYPES = {
    "UserStory",
    "FeatureCatalog",
    "DomainObject",
    "FieldSpec",
    "RuleAtom",
    "StateTransition",
    "TaskRule",
    "MessageAtom",
    "RolePermission",
    "IntegrationEndpoint",
    "ReportSpec",
    "DataMigrationSpec",
}

SYSTEM_ENTITY_TYPES = {
    "EvidenceSpan",
    "RuleVersion",
    "CanonicalTerm",
    "SourceDocument",
    "CandidateReviewItem",
}

FALLBACK_ENTITY_TYPES = {"CandidateEntity"}
ALLOWED_ENTITY_TYPES = TOP_LEVEL_ENTITY_TYPES | SYSTEM_ENTITY_TYPES | FALLBACK_ENTITY_TYPES

CORE_RELATION_TYPES = {
    "BelongsToFeature",
    "BelongsToDomain",
    "HasFieldSpec",
    "HasRuleAtom",
    "HasStateTransition",
    "HasTaskRule",
    "HasMessageAtom",
    "HasPermission",
    "HasIntegration",
    "HasReportSpec",
    "HasMigrationSpec",
    "ValidatesField",
    "ControlsRequired",
    "ControlsEditable",
    "ControlsDisplay",
    "ReadsMasterData",
    "CallsBackendApi",
    "IntegratesWith",
    "GeneratesTask",
    "AssignsHandler",
    "TransfersTask",
    "ClearsTask",
    "WritesAuditLog",
    "WritesOperationLog",
    "ReadsLedger",
    "WritesLedger",
    "HasReportFilter",
    "HasReportColumn",
    "MapsSourceToTarget",
    "Supersedes",
    "HasEvidence",
    "NormalizedTo",
    "DerivedFrom",
    "DependsOn",
}

SYSTEM_RELATION_TYPES = {
    "ExtractedFrom",
    "SupportedByEvidence",
    "HasVersion",
    "VersionConflictWith",
    "VersionReviewRequired",
    "DefinesVersion",
    "DerivedFromVersionEvidence",
    "HasCanonicalTerm",
    "ReviewRequiredFor",
    "AutoResolvedFrom",
    "HasUserStory",
    "HasFeatureCatalog",
}

ALLOWED_RELATION_TYPES = CORE_RELATION_TYPES | SYSTEM_RELATION_TYPES

FORBIDDEN_RELATION_TYPES = {
    "has_child",
    "belongs_to",
    "references_to",
    "queries_from",
    "queries_by",
    "contains",
}

ENTITY_TYPE_ALIASES = {
    "Attachment": "SourceDocument",
    "TextUnit": "EvidenceSpan",
    "SynonymTerm": "CanonicalTerm",
    "CandidateSynonym": "CanonicalTerm",
    "MasterDataObject": "DomainObject",
    "ReferenceDataObject": "DomainObject",
    "Currency": "DomainObject",
    "Country": "DomainObject",
    "HolidayCalendar": "DomainObject",
    "Counterparty": "DomainObject",
    "Bank": "DomainObject",
    "BankAccount": "DomainObject",
    "Instrument": "DomainObject",
    "Dealer": "DomainObject",
    "DealSet": "DomainObject",
    "Location": "DomainObject",
    "ValueSet": "DomainObject",
    "EnumValue": "DomainObject",
    "Transaction": "DomainObject",
    "Deal": "DomainObject",
    "DealAction": "DomainObject",
    "CashFlow": "DomainObject",
    "Ledger": "DomainObject",
    "LedgerEntry": "DomainObject",
    "LedgerStatus": "DomainObject",
    "LedgerDetail": "DomainObject",
    "HistoryRating": "DomainObject",
    "ReviewInformation": "DomainObject",
    "AdverseEvent": "DomainObject",
    "BankDefaultRecord": "DomainObject",
    "BalanceRecord": "DomainObject",
    "SettlementRecord": "DomainObject",
    "ConfigItem": "DomainObject",
    "FeatureSwitch": "DomainObject",
    "LookupConfig": "DomainObject",
    "ConfigGroup": "DomainObject",
    "ConfigValue": "DomainObject",
    "SystemParameter": "DomainObject",
    "RoutingRule": "DomainObject",
    "TemplateConfig": "DomainObject",
    "ReceiverConfig": "DomainObject",
    "BusinessLookup": "DomainObject",
    "BusinessRule": "RuleAtom",
    "ValidationRule": "RuleAtom",
    "RequiredRule": "RuleAtom",
    "ValueSetRule": "RuleAtom",
    "DefaultValueRule": "RuleAtom",
    "EditableRule": "RuleAtom",
    "DisplayRule": "RuleAtom",
    "CascadeRule": "RuleAtom",
    "CalculationRule": "RuleAtom",
    "SortingRule": "RuleAtom",
    "PaginationRule": "RuleAtom",
    "ExportRule": "RuleAtom",
    "ConflictRule": "RuleAtom",
    "DfxControl": "RuleAtom",
    "IdempotencyRule": "RuleAtom",
    "ConcurrencyRule": "RuleAtom",
    "DedupRule": "RuleAtom",
    "DataConsistencyRule": "RuleAtom",
    "Workflow": "StateTransition",
    "WorkflowNode": "StateTransition",
    "WorkflowState": "StateTransition",
    "ApprovalStep": "StateTransition",
    "ApprovalAction": "StateTransition",
    "RejectAction": "StateTransition",
    "TransferAction": "StateTransition",
    "CancelAction": "StateTransition",
    "SubmitAction": "StateTransition",
    "ResubmitAction": "StateTransition",
    "CloseAction": "StateTransition",
    "TodoTask": "TaskRule",
    "TaskReceiver": "TaskRule",
    "TaskStatus": "TaskRule",
    "CurrentHandler": "RolePermission",
    "WorkflowLog": "RuleAtom",
    "WarningMessage": "MessageAtom",
    "NotificationRule": "MessageAtom",
    "MonitoringRule": "ReportSpec",
    "AlertRule": "ReportSpec",
    "Indicator": "ReportSpec",
    "Metric": "ReportSpec",
    "Threshold": "ReportSpec",
    "RiskSignal": "ReportSpec",
    "TriggerCondition": "ReportSpec",
    "AbnormalEvent": "ReportSpec",
    "ExceptionEvent": "ReportSpec",
    "ScheduledCheck": "ReportSpec",
    "Report": "ReportSpec",
    "ReportTemplate": "ReportSpec",
    "ReportColumn": "ReportSpec",
    "ReportFilter": "ReportSpec",
    "SearchCondition": "ReportSpec",
    "QueryResult": "ReportSpec",
    "ExportFile": "ReportSpec",
    "ComparisonReport": "ReportSpec",
    "ConsistencyCheck": "ReportSpec",
    "CheckResult": "ReportSpec",
    "ReportTask": "ReportSpec",
    "ReportSheet": "ReportSpec",
    "FrontendApi": "IntegrationEndpoint",
    "BackendApi": "IntegrationEndpoint",
    "Endpoint": "IntegrationEndpoint",
    "Service": "IntegrationEndpoint",
    "RequestDto": "IntegrationEndpoint",
    "ResponseDto": "IntegrationEndpoint",
    "ApiField": "IntegrationEndpoint",
    "ExternalSystem": "IntegrationEndpoint",
    "MqTopic": "IntegrationEndpoint",
    "Event": "IntegrationEndpoint",
    "Callback": "IntegrationEndpoint",
    "IntegrationFlow": "IntegrationEndpoint",
    "BatchJob": "IntegrationEndpoint",
    "Scheduler": "IntegrationEndpoint",
    "InterfaceError": "IntegrationEndpoint",
    "IntegrationMessage": "IntegrationEndpoint",
    "Table": "IntegrationEndpoint",
    "Column": "FieldSpec",
    "Role": "RolePermission",
    "Permission": "RolePermission",
    "PermissionScope": "RolePermission",
    "DataScope": "RolePermission",
    "User": "RolePermission",
    "Operator": "RolePermission",
    "AuditRule": "RolePermission",
    "AuditLog": "RolePermission",
    "OperationLog": "RolePermission",
    "HistoryRecord": "RolePermission",
    "ApprovalHistory": "RolePermission",
    "AccessControl": "RolePermission",
    "ReviewerChecklist": "RolePermission",
    "ReviewResult": "RolePermission",
    "MigrationRule": "DataMigrationSpec",
    "MigrationTask": "DataMigrationSpec",
    "SourceSystem": "DataMigrationSpec",
    "TargetSystem": "DataMigrationSpec",
    "SourceTable": "DataMigrationSpec",
    "TargetTable": "DataMigrationSpec",
    "SourceColumn": "DataMigrationSpec",
    "TargetColumn": "DataMigrationSpec",
    "DataMapping": "DataMigrationSpec",
    "InitialDataRule": "DataMigrationSpec",
    "DataTransformRule": "DataMigrationSpec",
    "MigrationBatch": "DataMigrationSpec",
    "MigrationStatus": "DataMigrationSpec",
    "HistoricalData": "DataMigrationSpec",
    "OtherObject": "DomainObject",
    "UnclassifiedObject": "CandidateEntity",
}

RELATION_TYPE_ALIASES = {
    "BelongsToModule": "BelongsToFeature",
    "HasRuleVersion": "HasVersion",
    "References": "DependsOn",
    "RelatedTo": "DependsOn",
    "ConflictsWith": "DependsOn",
    "GeneratedFrom": "DerivedFrom",
    "UsesMasterData": "ReadsMasterData",
    "UsesReferenceData": "ReadsMasterData",
    "HasValueSet": "ReadsMasterData",
    "HasEnumValue": "ReadsMasterData",
    "HasCurrency": "ReadsMasterData",
    "HasCountry": "ReadsMasterData",
    "HasBankAccount": "ReadsMasterData",
    "UsesHolidayCalendar": "ReadsMasterData",
    "MaintainedBy": "WritesAuditLog",
    "DeactivatedBy": "WritesAuditLog",
    "HasWorkflow": "HasStateTransition",
    "HasWorkflowNode": "HasStateTransition",
    "HasWorkflowState": "HasStateTransition",
    "TransitionsTo": "HasStateTransition",
    "TriggeredBy": "HasStateTransition",
    "RequiresState": "HasStateTransition",
    "AllowsAction": "HasStateTransition",
    "BlocksAction": "HasStateTransition",
    "Approves": "HasStateTransition",
    "Rejects": "HasStateTransition",
    "TransfersTo": "TransfersTask",
    "UpdatesHandler": "AssignsHandler",
    "WritesWorkflowLog": "WritesOperationLog",
    "CreatesDeal": "WritesLedger",
    "UpdatesDeal": "WritesLedger",
    "DeletesDeal": "WritesLedger",
    "CopiesDeal": "WritesLedger",
    "HasDealAction": "WritesLedger",
    "GeneratesCashFlow": "WritesLedger",
    "UpdatesCashFlow": "WritesLedger",
    "GeneratesLedger": "WritesLedger",
    "UpdatesLedger": "WritesLedger",
    "RemovesFromLedger": "WritesLedger",
    "HasLedgerStatus": "ReadsLedger",
    "HasLedgerDetail": "ReadsLedger",
    "HasHistoryRating": "ReadsLedger",
    "HasReviewInformation": "ReadsLedger",
    "HasAdverseEvent": "ReadsLedger",
    "RecordsBalance": "WritesLedger",
    "HasBusinessRule": "HasRuleAtom",
    "HasValidationRule": "HasRuleAtom",
    "DefaultsTo": "ControlsDisplay",
    "CascadesTo": "ControlsDisplay",
    "CalculatesValue": "ControlsDisplay",
    "SortsBy": "ControlsDisplay",
    "PaginatesBy": "ControlsDisplay",
    "RequiresIdempotency": "HasRuleAtom",
    "RequiresConcurrencyControl": "HasRuleAtom",
    "RequiresDeduplication": "HasRuleAtom",
    "RequiresDataConsistency": "HasRuleAtom",
    "HasMonitoringRule": "HasReportSpec",
    "HasAlertRule": "HasReportSpec",
    "TriggersAlert": "HasReportSpec",
    "TriggersWarning": "HasMessageAtom",
    "CalculatesMetric": "HasReportSpec",
    "HasThreshold": "HasReportSpec",
    "DetectsRisk": "HasReportSpec",
    "GeneratesNotification": "HasMessageAtom",
    "SchedulesCheck": "HasReportSpec",
    "MonitorsObject": "HasReportSpec",
    "HasReport": "HasReportSpec",
    "HasReportTemplate": "HasReportSpec",
    "FiltersBy": "HasReportFilter",
    "ExportsReport": "HasReportSpec",
    "ComparesWith": "HasReportSpec",
    "HighlightsDifference": "HasReportSpec",
    "LinksToReportDetail": "HasReportSpec",
    "CallsFrontendApi": "CallsBackendApi",
    "CallsService": "CallsBackendApi",
    "ExposesEndpoint": "HasIntegration",
    "HasRequestDto": "HasIntegration",
    "HasResponseDto": "HasIntegration",
    "HasRequestField": "HasFieldSpec",
    "HasResponseField": "HasFieldSpec",
    "MapsToApiField": "HasFieldSpec",
    "PublishesToTopic": "IntegratesWith",
    "ConsumesFromTopic": "IntegratesWith",
    "ReceivesCallback": "IntegratesWith",
    "HandlesError": "HasRuleAtom",
    "RetriesOnFailure": "HasRuleAtom",
    "RequiresTimeout": "HasRuleAtom",
    "ReadsTable": "ReadsMasterData",
    "WritesTable": "WritesLedger",
    "MapsToColumn": "MapsSourceToTarget",
    "UsesConfigItem": "DependsOn",
    "UsesLookupConfig": "ReadsMasterData",
    "ControlledByConfig": "ControlsDisplay",
    "ControlledBySwitch": "ControlsDisplay",
    "HasConfigGroup": "BelongsToDomain",
    "HasConfigValue": "ControlsDisplay",
    "UsesSystemParameter": "DependsOn",
    "UsesRoutingRule": "DependsOn",
    "UsesTemplateConfig": "DependsOn",
    "UsesReceiverConfig": "DependsOn",
    "RequiresPermission": "HasPermission",
    "VisibleToRole": "HasPermission",
    "EditableByRole": "HasPermission",
    "OperatedBy": "HasPermission",
    "ReviewedBy": "HasPermission",
    "ConfirmedBy": "HasPermission",
    "ValidatedByReviewer": "HasPermission",
    "RecordsHistory": "WritesAuditLog",
    "HasPermissionScope": "HasPermission",
    "HasDataScope": "HasPermission",
    "HasMigrationRule": "HasMigrationSpec",
    "HasMigrationTask": "HasMigrationSpec",
    "MigratesFrom": "MapsSourceToTarget",
    "MigratesTo": "MapsSourceToTarget",
    "ReadsSourceTable": "MapsSourceToTarget",
    "WritesTargetTable": "MapsSourceToTarget",
    "MapsFromColumn": "MapsSourceToTarget",
    "TransformsData": "MapsSourceToTarget",
    "InitializesData": "HasMigrationSpec",
    "UsesHistoricalData": "HasMigrationSpec",
    "BelongsToMigrationBatch": "HasMigrationSpec",
    "HasMigrationStatus": "HasMigrationSpec",
}

FEATURE_RELATION_BY_ENTITY_TYPE = {
    "DomainObject": "BelongsToFeature",
    "FieldSpec": "HasFieldSpec",
    "RuleAtom": "HasRuleAtom",
    "StateTransition": "HasStateTransition",
    "TaskRule": "HasTaskRule",
    "MessageAtom": "HasMessageAtom",
    "RolePermission": "HasPermission",
    "IntegrationEndpoint": "HasIntegration",
    "ReportSpec": "HasReportSpec",
    "DataMigrationSpec": "HasMigrationSpec",
    "CandidateEntity": "ReviewRequiredFor",
}


@dataclass(frozen=True)
class TypeResolution:
    original: str | None
    resolved: str
    reason_code: str
    safe_to_use: bool


@dataclass(frozen=True)
class RelationResolution:
    original: str | None
    resolved: str | None
    reason_code: str
    safe_to_use: bool
    forbidden_original: bool = False


def resolve_entity_type(entity_type: str | None, *, section_type: str | None = None) -> TypeResolution:
    original = _clean(entity_type)
    if original in ALLOWED_ENTITY_TYPES:
        return TypeResolution(original, original or "CandidateEntity", "ALREADY_ALLOWED_ENTITY", True)
    if original in ENTITY_TYPE_ALIASES:
        return TypeResolution(original, ENTITY_TYPE_ALIASES[original], "ENTITY_ALIAS_RESOLVED", True)
    section_resolved = _entity_type_for_section(section_type)
    if section_resolved:
        return TypeResolution(original, section_resolved, "SECTION_ENTITY_RESOLVED", True)
    return TypeResolution(original, "CandidateEntity", "UNRESOLVED_ENTITY_TO_CANDIDATE", False)


def resolve_relation_type(
    relation_type: str | None,
    relationship_keywords: str | None = None,
    *,
    allowed_relation_types: list[str] | None = None,
    section_type: str | None = None,
    domain_code: str | None = None,
    source_entity_name: str | None = None,
    target_entity_type: str | None = None,
) -> RelationResolution:
    allowed = set(allowed_relation_types or [])
    original = _clean(relation_type)
    keywords = _clean(relationship_keywords)
    raw = original if original and original != "CandidateRelation" else keywords
    if not raw:
        return RelationResolution(original, None, "MISSING_RELATION_TYPE", False)

    lowered = raw.lower()
    if lowered in FORBIDDEN_RELATION_TYPES:
        resolved = _resolve_forbidden_relation(
            lowered,
            section_type=section_type,
            domain_code=domain_code,
            source_entity_name=source_entity_name,
            target_entity_type=target_entity_type,
        )
        if resolved:
            return RelationResolution(raw, resolved, "FORBIDDEN_RELATION_RESOLVED", True, True)
        return RelationResolution(raw, None, "FORBIDDEN_RELATION_UNRESOLVED", False, True)

    if raw in ALLOWED_RELATION_TYPES:
        return RelationResolution(raw, raw, "ALLOWED_RELATION", True)

    if raw in RELATION_TYPE_ALIASES:
        resolved = RELATION_TYPE_ALIASES[raw]
        return RelationResolution(raw, resolved, "RELATION_ALIAS_RESOLVED", True)

    if raw in allowed:
        alias = RELATION_TYPE_ALIASES.get(raw)
        if alias:
            return RelationResolution(raw, alias, "ALLOWED_RELATION_ALIAS_RESOLVED", True)

    return RelationResolution(raw, None, "INVALID_RELATION_TYPE", False)


def feature_relation_type(entity_type: str) -> str:
    return FEATURE_RELATION_BY_ENTITY_TYPE.get(entity_type, "BelongsToFeature")


def is_allowed_relation_type(relation_type: str | None) -> bool:
    return bool(relation_type and relation_type in ALLOWED_RELATION_TYPES)


def _resolve_forbidden_relation(
    relation_type: str,
    *,
    section_type: str | None,
    domain_code: str | None,
    source_entity_name: str | None,
    target_entity_type: str | None,
) -> str | None:
    if relation_type == "has_child":
        if target_entity_type:
            relation = feature_relation_type(target_entity_type)
            return None if relation == "ReviewRequiredFor" else relation
        return {
            "field_table": "HasFieldSpec",
            "business_rule": "HasRuleAtom",
            "state_rule": "HasStateTransition",
            "task_rule": "HasTaskRule",
            "message_rule": "HasMessageAtom",
            "report_rule": "HasReportColumn",
            "migration_rule": "HasMigrationSpec",
            "api_desc": "HasIntegration",
        }.get(section_type)
    if relation_type == "belongs_to":
        if source_entity_name and ":" in source_entity_name:
            return "BelongsToFeature"
        return "BelongsToDomain"
    if relation_type in {"queries_from", "queries_by"}:
        if domain_code == "MonitoringReport" or section_type == "report_rule":
            return "HasReportFilter"
        return None
    if relation_type == "contains":
        return {
            "field_table": "HasFieldSpec",
            "business_rule": "HasRuleAtom",
            "report_rule": "HasReportColumn",
            "migration_rule": "HasMigrationSpec",
        }.get(section_type)
    if relation_type == "references_to":
        if domain_code == "MasterData":
            return "ReadsMasterData"
        return "DependsOn"
    return None


def _entity_type_for_section(section_type: str | None) -> str | None:
    return {
        "field_table": "FieldSpec",
        "business_rule": "RuleAtom",
        "state_rule": "StateTransition",
        "task_rule": "TaskRule",
        "message_rule": "MessageAtom",
        "api_desc": "IntegrationEndpoint",
        "report_rule": "ReportSpec",
        "migration_rule": "DataMigrationSpec",
        "dfx_rule": "RuleAtom",
    }.get(section_type or "")


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "ALLOWED_ENTITY_TYPES",
    "ALLOWED_RELATION_TYPES",
    "CORE_RELATION_TYPES",
    "FALLBACK_ENTITY_TYPES",
    "FORBIDDEN_RELATION_TYPES",
    "RelationResolution",
    "SYSTEM_ENTITY_TYPES",
    "SYSTEM_RELATION_TYPES",
    "TOP_LEVEL_ENTITY_TYPES",
    "TypeResolution",
    "feature_relation_type",
    "is_allowed_relation_type",
    "resolve_entity_type",
    "resolve_relation_type",
]
