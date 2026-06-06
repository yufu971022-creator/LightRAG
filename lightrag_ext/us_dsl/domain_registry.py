from __future__ import annotations

from dataclasses import dataclass, field


DOMAIN_MASTER_DATA = "MasterData"
DOMAIN_WORKFLOW = "Workflow"
DOMAIN_LEDGER = "Ledger"
DOMAIN_RULE_MANAGEMENT = "RuleManagement"
DOMAIN_MONITORING_REPORT = "MonitoringReport"
DOMAIN_INTEGRATION = "Integration"
DOMAIN_CONFIGURATION = "Configuration"
DOMAIN_ACCESS_AUDIT = "AccessAudit"
DOMAIN_DATA_MIGRATION = "DataMigrationInitialization"
DOMAIN_OTHER = "Other"

SYSTEM_ENTITY_TYPES = {
    "SourceDocument",
    "UserStory",
    "FeatureCatalog",
    "EvidenceSpan",
    "RuleVersion",
    "CanonicalTerm",
}
SYSTEM_RELATION_TYPES = {
    "HasUserStory",
    "HasFeatureCatalog",
    "SupportedByEvidence",
    "HasVersion",
    "NormalizedTo",
    "DerivedFrom",
}


@dataclass(frozen=True)
class DomainConfig:
    domain_code: str
    display_name: str
    allowed_entity_types: set[str]
    allowed_relation_types: set[str]
    default_section_types: set[str] = field(default_factory=set)
    required_evidence_fields: set[str] = field(
        default_factory=lambda: {"sourceUsId", "textUnitId", "textHash", "evidenceText"}
    )
    high_risk: bool = False
    default_policy: dict = field(default_factory=dict)


class DomainRegistry:
    def __init__(self, domains: dict[str, DomainConfig] | None = None) -> None:
        self._domains = domains or _default_domains()

    def get(self, domain_code: str | None) -> DomainConfig:
        return self._domains[self.normalize_domain(domain_code)]

    def validate_domain(self, domain_code: str | None) -> bool:
        return self.normalize_domain(domain_code) in self._domains

    def normalize_domain(self, domain_code: str | None) -> str:
        if not domain_code:
            return DOMAIN_OTHER
        for known in self._domains:
            if known.lower() == str(domain_code).strip().lower():
                return known
        return DOMAIN_OTHER

    def allowed_entity_types(self, domain_code: str | None) -> set[str]:
        return set(self.get(domain_code).allowed_entity_types) | SYSTEM_ENTITY_TYPES

    def allowed_relation_types(self, domain_code: str | None) -> set[str]:
        return set(self.get(domain_code).allowed_relation_types) | SYSTEM_RELATION_TYPES

    def all_domain_codes(self) -> set[str]:
        return set(self._domains)


def default_domain_registry() -> DomainRegistry:
    return DomainRegistry()


def _default_domains() -> dict[str, DomainConfig]:
    return {
        DOMAIN_MASTER_DATA: DomainConfig(
            domain_code=DOMAIN_MASTER_DATA,
            display_name="Master Data",
            allowed_entity_types={
                "DomainObject",
                "FieldSpec",
                "RuleAtom",
                "CanonicalTerm",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "HasFieldSpec",
                "ReadsMasterData",
                "NormalizedTo",
                "HasRuleAtom",
                "HasUserStory",
                "HasFeatureCatalog",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
        ),
        DOMAIN_WORKFLOW: DomainConfig(
            domain_code=DOMAIN_WORKFLOW,
            display_name="Workflow",
            allowed_entity_types={
                "FeatureCatalog",
                "TaskRule",
                "StateTransition",
                "RolePermission",
                "MessageAtom",
                "RuleAtom",
                "SourceDocument",
                "UserStory",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "GeneratesTask",
                "AssignsHandler",
                "TransfersTask",
                "ClearsTask",
                "HasTaskRule",
                "HasStateTransition",
                "RequiresPermission",
                "HasPermission",
                "HasMessageAtom",
                "HasRuleAtom",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
        ),
        DOMAIN_LEDGER: DomainConfig(
            domain_code=DOMAIN_LEDGER,
            display_name="Ledger",
            allowed_entity_types={
                "DomainObject",
                "FieldSpec",
                "RuleAtom",
                "ReportSpec",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "WritesLedger",
                "ReadsLedger",
                "HasFieldSpec",
                "HasRuleAtom",
                "HasUserStory",
                "HasFeatureCatalog",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
        ),
        DOMAIN_RULE_MANAGEMENT: DomainConfig(
            domain_code=DOMAIN_RULE_MANAGEMENT,
            display_name="Rule Management",
            allowed_entity_types={
                "RuleAtom",
                "RuleVersion",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
            },
            allowed_relation_types={
                "HasRuleAtom",
                "HasVersion",
                "Supersedes",
                "VersionReviewRequired",
                "VersionConflictWith",
                "DefinesVersion",
                "DerivedFromVersionEvidence",
                "SupportedByEvidence",
                "DerivedFrom",
            },
            high_risk=True,
        ),
        DOMAIN_MONITORING_REPORT: DomainConfig(
            domain_code=DOMAIN_MONITORING_REPORT,
            display_name="Monitoring Report",
            allowed_entity_types={
                "ReportSpec",
                "FieldSpec",
                "RuleAtom",
                "StateTransition",
                "DomainObject",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "HasReportFilter",
                "HasReportColumn",
                "ReadsLedger",
                "HasFieldSpec",
                "HasStateTransition",
                "HasRuleAtom",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
        ),
        DOMAIN_INTEGRATION: DomainConfig(
            domain_code=DOMAIN_INTEGRATION,
            display_name="Integration",
            allowed_entity_types={
                "IntegrationEndpoint",
                "FieldSpec",
                "DomainObject",
                "RuleAtom",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "CallsBackendApi",
                "IntegratesWith",
                "HasIntegration",
                "HasFieldSpec",
                "HasRuleAtom",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
        ),
        DOMAIN_CONFIGURATION: DomainConfig(
            domain_code=DOMAIN_CONFIGURATION,
            display_name="Configuration",
            allowed_entity_types={
                "DomainObject",
                "FieldSpec",
                "RuleAtom",
                "CanonicalTerm",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "HasConfig",
                "NormalizedTo",
                "HasRuleAtom",
                "HasFieldSpec",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
        ),
        DOMAIN_ACCESS_AUDIT: DomainConfig(
            domain_code=DOMAIN_ACCESS_AUDIT,
            display_name="Access Audit",
            allowed_entity_types={
                "RolePermission",
                "RuleAtom",
                "MessageAtom",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "RequiresPermission",
                "WritesAuditLog",
                "WritesOperationLog",
                "HasPermission",
                "HasRuleAtom",
                "HasMessageAtom",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
            high_risk=True,
        ),
        DOMAIN_DATA_MIGRATION: DomainConfig(
            domain_code=DOMAIN_DATA_MIGRATION,
            display_name="Data Migration Initialization",
            allowed_entity_types={
                "DataMigrationSpec",
                "FieldSpec",
                "RuleAtom",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "MapsSourceToTarget",
                "HasMigrationSpec",
                "ValidatesField",
                "HasFieldSpec",
                "HasRuleAtom",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
        ),
        DOMAIN_OTHER: DomainConfig(
            domain_code=DOMAIN_OTHER,
            display_name="Other",
            allowed_entity_types={
                "CandidateEntity",
                "RuleAtom",
                "SourceDocument",
                "UserStory",
                "FeatureCatalog",
                "EvidenceSpan",
                "RuleVersion",
            },
            allowed_relation_types={
                "CandidateRelation",
                "DependsOn",
                "SupportedByEvidence",
                "HasVersion",
                "DerivedFrom",
            },
        ),
    }


__all__ = [
    "DomainConfig",
    "DomainRegistry",
    "default_domain_registry",
]
