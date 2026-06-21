from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RelationTypeSignature:
    relation_type: str
    allowed_source_types: set[str] = field(default_factory=set)
    allowed_target_types: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class RelationSignatureValidation:
    relation_type: str
    source_type: str
    target_type: str
    valid: bool
    issue_code: str | None = None


class RelationTypeSignatureRegistry:
    def __init__(self, signatures: dict[str, RelationTypeSignature] | None = None) -> None:
        self._signatures = signatures or _default_signatures()

    def get(self, relation_type: str) -> RelationTypeSignature | None:
        return self._signatures.get(relation_type)

    def validate(self, relation_type: str, source_type: str, target_type: str) -> RelationSignatureValidation:
        signature = self.get(relation_type)
        if signature is None:
            return RelationSignatureValidation(relation_type, source_type, target_type, False, "UNKNOWN_RELATION_SIGNATURE")
        valid = source_type in signature.allowed_source_types and target_type in signature.allowed_target_types
        return RelationSignatureValidation(
            relation_type=relation_type,
            source_type=source_type,
            target_type=target_type,
            valid=valid,
            issue_code=None if valid else "INVALID_RELATION_SIGNATURE",
        )

    def type_for_role(self, relation_type: str | None, relation_role: str | None) -> str | None:
        if not relation_type or not relation_role:
            return None
        signature = self.get(relation_type)
        if signature is None:
            return None
        if relation_role in {"source", "subject", "src"} and len(signature.allowed_source_types) == 1:
            return next(iter(signature.allowed_source_types))
        if relation_role in {"target", "object", "tgt"} and len(signature.allowed_target_types) == 1:
            return next(iter(signature.allowed_target_types))
        return None

    def to_report(self) -> dict[str, Any]:
        return {
            key: {
                "source": sorted(value.allowed_source_types),
                "target": sorted(value.allowed_target_types),
            }
            for key, value in sorted(self._signatures.items())
        }


def default_relation_type_signature_registry() -> RelationTypeSignatureRegistry:
    return RelationTypeSignatureRegistry()


def _default_signatures() -> dict[str, RelationTypeSignature]:
    signatures = [
        RelationTypeSignature("HasReportFilter", {"ReportSpec", "FeatureCatalog"}, {"FieldSpec"}),
        RelationTypeSignature("HasReportColumn", {"ReportSpec"}, {"FieldSpec"}),
        RelationTypeSignature("AssignsHandler", {"TaskRule"}, {"RolePermission"}),
        RelationTypeSignature("TransfersTask", {"TaskRule"}, {"TaskRule", "RolePermission"}),
        RelationTypeSignature("CallsBackendApi", {"FeatureCatalog", "RuleAtom", "TaskRule", "ReportSpec"}, {"IntegrationEndpoint"}),
        RelationTypeSignature("HasFieldSpec", {"FeatureCatalog", "DomainObject", "ReportSpec", "IntegrationEndpoint", "DataMigrationSpec"}, {"FieldSpec"}),
        RelationTypeSignature("HasVersion", {"FieldSpec", "RuleAtom", "TaskRule", "StateTransition", "IntegrationEndpoint", "ReportSpec", "RolePermission", "DataMigrationSpec"}, {"RuleVersion"}),
        RelationTypeSignature("HasMigrationSpec", {"FeatureCatalog", "DataMigrationSpec"}, {"DataMigrationSpec", "FieldSpec"}),
    ]
    return {signature.relation_type: signature for signature in signatures}
