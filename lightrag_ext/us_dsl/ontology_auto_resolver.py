from __future__ import annotations

import re
from dataclasses import dataclass

from .candidate_types import CandidateEntity, CandidateRelation
from .config_registry import ConfigRegistry, DEFAULT_CONFIG_REGISTRY
from .extraction_metrics import detect_relation_type, is_snake_case_relation


@dataclass(frozen=True)
class OntologyResolveResult:
    resolved: bool
    original_type: str | None
    resolved_type: str | None
    original_relation_type: str | None
    resolved_relation_type: str | None
    reason_code: str
    reason: str
    confidence_score_delta: float
    safe_to_auto_resolve: bool
    requires_human_review: bool
    issues: list[str]


def resolve_candidate_ontology(
    candidate: CandidateEntity | CandidateRelation,
    *,
    allowed_entity_types: list[str] | None = None,
    allowed_relation_types: list[str] | None = None,
    domain_code: str | None = None,
    section_type: str | None = None,
    feature_key: str | None = None,
    evidence_text: str | None = None,
    known_objects: list[dict] | None = None,
    registry: ConfigRegistry | None = None,
) -> OntologyResolveResult:
    registry = registry or DEFAULT_CONFIG_REGISTRY
    if isinstance(candidate, CandidateEntity):
        return _resolve_entity(
            candidate,
            allowed_entity_types=allowed_entity_types or [],
            domain_code=domain_code or candidate.domain_code,
            section_type=section_type or candidate.section_type,
            feature_key=feature_key or candidate.feature_key,
            evidence_text=evidence_text or candidate.evidence_text or "",
            known_objects=known_objects or [],
            registry=registry,
        )
    return _resolve_relation(
        candidate,
        allowed_relation_types=allowed_relation_types or [],
        domain_code=domain_code or candidate.domain_code,
        section_type=section_type or candidate.section_type,
        feature_key=feature_key or candidate.feature_key,
        evidence_text=evidence_text or candidate.evidence_text or "",
        known_objects=known_objects or [],
        registry=registry,
    )


def _resolve_entity(
    candidate: CandidateEntity,
    *,
    allowed_entity_types: list[str],
    domain_code: str | None,
    section_type: str | None,
    feature_key: str | None,
    evidence_text: str,
    known_objects: list[dict],
    registry: ConfigRegistry,
) -> OntologyResolveResult:
    original = candidate.entity_type
    if original in allowed_entity_types:
        return _result(True, original, original, None, None, "ALREADY_ALLOWED_ENTITY", "Entity type is already allowed.")

    lowered = original.lower()
    entity_name = candidate.entity_name
    evidence_lower = evidence_text.lower()

    if _context_mismatch_for_entity(candidate, domain_code, section_type, evidence_text):
        return _result(
            True,
            original,
            None,
            None,
            None,
            "CONTEXT_MISMATCH_INFO_ONLY",
            "Candidate appears to be cross-context extraction noise; keep as info-only, no human review.",
            delta=0.0,
        )

    registry_alias = _resolve_entity_alias_from_registry(
        original,
        allowed_entity_types,
        domain_code,
        section_type,
        evidence_text,
        registry,
    )
    if registry_alias:
        resolved_type, reason_code = registry_alias
        return _result(True, original, resolved_type, None, None, reason_code, f"Entity alias maps to {resolved_type}.")

    if lowered in {"action", "buttonaction", "useraction"}:
        resolved = _resolve_action_entity(allowed_entity_types, section_type, domain_code, evidence_text)
        if resolved:
            return _result(True, original, resolved, None, None, "ACTION_TO_WORKFLOW_ACTION", f"Action maps to {resolved}.")

    if lowered in {"message", "prompt", "errormessage"} and "MessageAtom" in allowed_entity_types:
        return _result(True, original, "MessageAtom", None, None, "MESSAGE_TO_MESSAGE_ATOM", "Message-like type maps to MessageAtom.")

    if (
        lowered in {"audit", "log", "audithistory"}
        or "audit history" in entity_name.lower()
    ):
        for target in ("AuditLog", "OperationLog", "WorkflowLog"):
            if target in allowed_entity_types and (target != "OperationLog" or "operationlog" in evidence_lower):
                return _result(True, original, target, None, None, "LOG_TO_LOG_ENTITY", f"Log-like entity maps to {target}.")

    if lowered in {"reportfield", "queryfield", "filterfield"}:
        if domain_code == "MonitoringReport" and "SearchCondition" in allowed_entity_types:
            return _result(True, original, "SearchCondition", None, None, "REPORT_FIELD_TO_SEARCH_CONDITION", "Report query field maps to SearchCondition.")
        if "ReportColumn" in allowed_entity_types and _contains_any(evidence_lower, ("result", "column", "展示", "结果列")):
            return _result(True, original, "ReportColumn", None, None, "REPORT_FIELD_TO_REPORT_COLUMN", "Report output field maps to ReportColumn.")

    if lowered in {"api", "interface", "endpoint"}:
        for target in ("BackendApi", "FrontendApi", "ExternalSystem"):
            if target in allowed_entity_types:
                return _result(True, original, target, None, None, "API_TO_INTERFACE_ENTITY", f"API-like type maps to {target}.")

    if lowered in {"config", "lookup", "switch"}:
        if "LookupConfig" in allowed_entity_types and _contains_any(evidence_lower, ("lookup", "值集")):
            return _result(True, original, "LookupConfig", None, None, "LOOKUP_TO_LOOKUP_CONFIG", "Lookup evidence maps to LookupConfig.")
        for target in ("FeatureSwitch", "ConfigItem"):
            if target in allowed_entity_types:
                return _result(True, original, target, None, None, "CONFIG_TO_CONFIG_ENTITY", f"Config-like type maps to {target}.")

    business_name_mapping = _business_object_entity_mapping(
        original,
        entity_name,
        allowed_entity_types,
        section_type,
        registry,
    )
    if business_name_mapping:
        return _result(True, original, business_name_mapping, None, None, "BUSINESS_NAME_TO_ENTITY_TYPE", f"Business object name maps to {business_name_mapping}.")

    if original == "CandidateEntity":
        resolved = _resolve_candidate_entity_from_known_objects(
            candidate,
            allowed_entity_types,
            known_objects,
        )
        if resolved:
            return _result(True, original, resolved, None, None, "CANDIDATE_ENTITY_KNOWN_OBJECT_MATCH", f"Known objects map candidate to {resolved}.")

    return _unresolved(original_type=original, reason="Entity type cannot be safely auto-resolved.")


def _resolve_relation(
    candidate: CandidateRelation,
    *,
    allowed_relation_types: list[str],
    domain_code: str | None,
    section_type: str | None,
    feature_key: str | None,
    evidence_text: str,
    known_objects: list[dict],
    registry: ConfigRegistry,
) -> OntologyResolveResult:
    original = candidate.relation_type
    keywords = candidate.relationship_keywords
    if not evidence_text or not candidate.source_entity_name or not candidate.target_entity_name:
        return _unresolved(original_relation_type=original, reason="Relation lacks evidence or endpoints.")

    detected = detect_relation_type(keywords, allowed_relation_types)
    if detected and detected != "CandidateRelation":
        return _result(True, None, None, original, detected, "ALLOWED_RELATION_KEYWORD", f"Keywords contain allowed relation {detected}.")

    if _context_mismatch_for_relation(candidate, domain_code, section_type, evidence_text):
        return _result(
            True,
            None,
            None,
            original,
            None,
            "CONTEXT_MISMATCH_INFO_ONLY",
            "Relation appears to be cross-context extraction noise; keep as info-only, no human review.",
            delta=0.0,
        )

    lowered = keywords.lower().strip()
    evidence_lower = evidence_text.lower()
    source = candidate.source_entity_name

    registry_relation = _resolve_relation_from_registry(
        lowered,
        allowed_relation_types,
        domain_code,
        evidence_text,
        source,
        feature_key,
        registry,
    )
    if registry_relation:
        resolved_relation, reason_code = registry_relation
        return _result(True, None, None, original, resolved_relation, reason_code, f"Relation maps to {resolved_relation}.")
    if lowered == "has_child":
        return _unresolved(original_relation_type=original, reason="Ambiguous has_child relation.")

    if lowered == "belongs_to":
        for target_type in ("BelongsToDomain", "BelongsToModule"):
            if target_type in allowed_relation_types:
                return _result(True, None, None, original, target_type, "BELONGS_TO_DOMAIN_OR_MODULE", f"belongs_to maps to {target_type}.")
        return _unresolved(original_relation_type=original, reason="Ambiguous belongs_to relation.")

    if lowered == "references_to":
        if "References" in allowed_relation_types:
            return _result(True, None, None, original, "References", "REFERENCE_GENERIC", "Generic reference maps to References.")
        return _unresolved(original_relation_type=original, reason="Ambiguous references_to relation.")

    if lowered in {"queries_from", "queries_by"}:
        for target_type in ("FiltersBy", "HasReportFilter", "LinksToReportDetail"):
            if domain_code == "MonitoringReport" and target_type in allowed_relation_types:
                return _result(True, None, None, original, target_type, "QUERY_RELATION_TO_REPORT_RELATION", f"Query relation maps to {target_type}.")
        return _unresolved(original_relation_type=original, reason="Ambiguous query relation.")

    if lowered == "contains":
        return _unresolved(original_relation_type=original, reason="Ambiguous contains relation.")

    if _contains_any(lowered, ("validates", "controls", "checks")):
        for target_type in ("ValidatesField", "ControlsRequired", "ControlsEditable", "ControlsDisplay"):
            if target_type in allowed_relation_types:
                return _result(True, None, None, original, target_type, "CONTROL_RELATION_TO_RULE_RELATION", f"Control relation maps to {target_type}.")

    if _contains_any(lowered, ("writes", "records")) or _contains_any(evidence_lower, ("audit history", "operationlog", "workflowlog")):
        for target_type in ("WritesAuditLog", "WritesOperationLog", "WritesWorkflowLog"):
            if target_type in allowed_relation_types:
                return _result(True, None, None, original, target_type, "LOG_WRITE_RELATION", f"Log write relation maps to {target_type}.")

    if _contains_any(lowered, ("calls", "invokes", "integrates")):
        for target_type in ("CallsBackendApi", "IntegratesWith", "PublishesToTopic", "ConsumesFromTopic"):
            if target_type in allowed_relation_types:
                return _result(True, None, None, original, target_type, "INTEGRATION_RELATION", f"Integration relation maps to {target_type}.")

    if _contains_any(lowered, ("generates", "creates")) or _contains_any(evidence_lower, ("task", "待办", "transfer to")):
        for target_type in ("GeneratesTask", "AssignsHandler", "TransfersTask", "ClearsTask"):
            if target_type in allowed_relation_types:
                return _result(True, None, None, original, target_type, "TASK_RELATION", f"Task relation maps to {target_type}.")

    if candidate.relation_type == "CandidateRelation":
        resolved = _resolve_candidate_relation_from_known_objects(candidate, allowed_relation_types, known_objects)
        if resolved:
            return _result(True, None, None, original, resolved, "CANDIDATE_RELATION_KNOWN_OBJECT_MATCH", f"Known objects map candidate relation to {resolved}.")

    if is_snake_case_relation(keywords):
        return _unresolved(original_relation_type=original, reason="Snake_case relation lacks safe mapping.")
    return _unresolved(original_relation_type=original, reason="Relation type cannot be safely auto-resolved.")


def _context_mismatch_for_entity(
    candidate: CandidateEntity,
    domain_code: str | None,
    section_type: str | None,
    evidence_text: str,
) -> bool:
    if domain_code == "MonitoringReport" and candidate.entity_type in {
        "ApprovalAction",
        "Workflow",
        "WorkflowLog",
    }:
        evidence_lower = evidence_text.lower()
        name_lower = candidate.entity_name.lower()
        return name_lower not in evidence_lower and "approve" not in evidence_lower
    return False


def _context_mismatch_for_relation(
    candidate: CandidateRelation,
    domain_code: str | None,
    section_type: str | None,
    evidence_text: str,
) -> bool:
    if domain_code == "MonitoringReport" and candidate.relationship_keywords in {
        "WritesWorkflowLog",
        "Approves",
        "HasWorkflow",
    }:
        evidence_lower = evidence_text.lower()
        return not _contains_any(evidence_lower, ("approve", "audit history", "workflow"))
    return False


def _resolve_action_entity(
    allowed_entity_types: list[str],
    section_type: str | None,
    domain_code: str | None,
    evidence_text: str,
) -> str | None:
    evidence_lower = evidence_text.lower()
    workflow_context = section_type in {"state_rule", "task_rule"} or domain_code == "Workflow"
    if not workflow_context:
        return None
    if "ApprovalAction" in allowed_entity_types and _contains_any(evidence_lower, ("approve", "reject", "submit", "return", "transfer", "转审")):
        return "ApprovalAction"
    if "SubmitAction" in allowed_entity_types and "submit" in evidence_lower:
        return "SubmitAction"
    if "TransferAction" in allowed_entity_types and _contains_any(evidence_lower, ("transfer", "transfer to", "转审")):
        return "TransferAction"
    return None


def _business_object_entity_mapping(
    original_type: str,
    entity_name: str,
    allowed_entity_types: list[str],
    section_type: str | None,
    registry: ConfigRegistry,
) -> str | None:
    values = {original_type, entity_name}
    for rule in registry.business_object_type_mapping:
        if rule.section_types and section_type not in rule.section_types:
            continue
        if not any(re.fullmatch(rule.source_type_pattern, value or "") for value in values):
            continue
        for target in rule.resolved_type_preferences:
            if target in allowed_entity_types:
                return target
    return None


def _resolve_entity_alias_from_registry(
    original_type: str,
    allowed_entity_types: list[str],
    domain_code: str | None,
    section_type: str | None,
    evidence_text: str,
    registry: ConfigRegistry,
) -> tuple[str, str] | None:
    lowered = original_type.lower()
    evidence_lower = evidence_text.lower()
    for rule in registry.entity_alias_rules:
        if lowered not in {source.lower() for source in rule.source_types}:
            continue
        if rule.resolved_type not in allowed_entity_types:
            continue
        if rule.domains and domain_code not in rule.domains:
            continue
        if rule.section_types and section_type not in rule.section_types:
            continue
        if rule.evidence_keywords and not _contains_any(evidence_lower, rule.evidence_keywords):
            continue
        return rule.resolved_type, rule.reason_code
    return None


def _resolve_relation_from_registry(
    original_relation: str,
    allowed_relation_types: list[str],
    domain_code: str | None,
    evidence_text: str,
    source_entity_name: str,
    feature_key: str | None,
    registry: ConfigRegistry,
) -> tuple[str, str] | None:
    evidence_lower = evidence_text.lower()
    for rule in registry.relation_mapping_rules:
        if original_relation != rule.original_relation:
            continue
        if rule.resolved_relation not in allowed_relation_types:
            continue
        if rule.domains and domain_code not in rule.domains:
            continue
        if rule.source_must_be_feature and not _source_is_feature(source_entity_name, feature_key):
            continue
        if rule.evidence_keywords and not _contains_any(evidence_lower, rule.evidence_keywords):
            continue
        return rule.resolved_relation, rule.reason_code
    return None


def _resolve_candidate_entity_from_known_objects(
    candidate: CandidateEntity,
    allowed_entity_types: list[str],
    known_objects: list[dict],
) -> str | None:
    for item in known_objects:
        if not isinstance(item, dict):
            continue
        if item.get("entityName") == candidate.entity_name:
            entity_type = item.get("entityType")
            if isinstance(entity_type, str) and entity_type in allowed_entity_types:
                return entity_type
    return None


def _resolve_candidate_relation_from_known_objects(
    candidate: CandidateRelation,
    allowed_relation_types: list[str],
    known_objects: list[dict],
) -> str | None:
    for item in known_objects:
        if not isinstance(item, dict):
            continue
        relation_type = item.get("relationType")
        if isinstance(relation_type, str) and relation_type in allowed_relation_types:
            source = item.get("sourceEntity")
            target = item.get("targetEntity")
            if source == candidate.source_entity_name or target == candidate.target_entity_name:
                return relation_type
    return None


def _source_is_feature(source: str, feature_key: str | None) -> bool:
    return bool(feature_key and source == feature_key) or ":" in source


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle.lower() in value for needle in needles)


def _result(
    resolved: bool,
    original_type: str | None,
    resolved_type: str | None,
    original_relation_type: str | None,
    resolved_relation_type: str | None,
    reason_code: str,
    reason: str,
    *,
    delta: float = 0.15,
) -> OntologyResolveResult:
    return OntologyResolveResult(
        resolved=resolved,
        original_type=original_type,
        resolved_type=resolved_type,
        original_relation_type=original_relation_type,
        resolved_relation_type=resolved_relation_type,
        reason_code=reason_code,
        reason=reason,
        confidence_score_delta=delta,
        safe_to_auto_resolve=resolved,
        requires_human_review=not resolved,
        issues=[],
    )


def _unresolved(
    *,
    original_type: str | None = None,
    original_relation_type: str | None = None,
    reason: str,
) -> OntologyResolveResult:
    return OntologyResolveResult(
        resolved=False,
        original_type=original_type,
        resolved_type=None,
        original_relation_type=original_relation_type,
        resolved_relation_type=None,
        reason_code="UNRESOLVED_ONTOLOGY",
        reason=reason,
        confidence_score_delta=0.0,
        safe_to_auto_resolve=False,
        requires_human_review=True,
        issues=["UNRESOLVED_ONTOLOGY"],
    )


__all__ = ["OntologyResolveResult", "resolve_candidate_ontology"]
