from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .domain_registry import DOMAIN_OTHER, default_domain_registry


IngestionRequestMode = Literal["raw", "dsl", "auto", "shadow"]
RouteDecision = Literal["DSL_FULL", "DSL_PARTIAL", "RAW_ONLY", "PARSE_FAILED"]
RiskCategory = Literal["version", "evidence", "type", "structure", "domain"]

DESIGN_MARKERS = {
    "user story": 2.0,
    "acceptance criteria": 2.0,
    "business rule": 1.5,
    "field": 1.0,
    "relationship": 1.0,
    "entity": 1.0,
    "source": 1.0,
    "evidence": 1.0,
    "given": 0.5,
    "when": 0.5,
    "then": 0.5,
}
STRUCTURE_MARKERS = {
    "user story",
    "acceptance criteria",
    "business rule",
    "field",
    "relationship",
    "entity",
    "source",
    "evidence",
    "given",
    "when",
    "then",
}
STOP_OBJECT_LABELS = {
    "acceptance criteria",
    "business rule",
    "domain",
    "entity",
    "evidence",
    "feature",
    "given",
    "relationship",
    "source",
    "then",
    "type",
    "user story",
    "when",
}
DOMAIN_KEYWORDS = {
    "MasterData": {"master data", "bank status", "query condition", "canonical", "reference data"},
    "Workflow": {"workflow", "task", "approval", "state transition", "handler"},
    "Ledger": {"ledger", "posting", "balance", "journal", "accounting"},
    "RuleManagement": {"rule version", "supersedes", "version conflict", "rule atom"},
    "MonitoringReport": {"report", "filter", "column", "dashboard", "monitoring"},
    "Integration": {"api", "integration", "endpoint", "backend", "interface"},
    "Configuration": {"configuration", "setting", "parameter", "toggle"},
    "AccessAudit": {"audit", "permission", "role", "access"},
    "DataMigrationInitialization": {"migration", "initialization", "cutover", "backfill"},
}
VERSION_TERMS = {"version", "v1", "v2", "supersedes", "deprecated", "override", "migration"}
TYPE_RISK_TERMS = {"tbd", "unknown", "misc", "thing", "object?", "unclear type"}
EVIDENCE_TERMS = {"source", "evidence", "us-", "user story", "acceptance criteria", "text unit"}
OBJECT_PATTERN = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3}\b")
US_PATTERN = re.compile(r"\bUS[-_ ]?\d+\b", re.IGNORECASE)


@dataclass(frozen=True)
class UnifiedIngestionRequest:
    document_id: str
    content: str
    mode: IngestionRequestMode = "shadow"
    file_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    allow_generic_graph_fallback: bool = False


@dataclass(frozen=True)
class IngestionProtocolOptions:
    min_full_score: float = 0.70
    min_partial_score: float = 0.35
    min_evidence_coverage_for_full: float = 0.35
    max_high_risk_objects_for_full: int = 0
    preserve_raw_text: bool = True


@dataclass(frozen=True)
class SemanticObjectCandidate:
    object_id: str
    label: str
    inferred_type: str
    evidence_line_numbers: list[int] = field(default_factory=list)
    risk_categories: list[RiskCategory] = field(default_factory=list)


@dataclass(frozen=True)
class ObjectRiskSummary:
    object_id: str
    label: str
    risk_category: RiskCategory
    severity: str
    reason: str
    line_number: int | None = None


@dataclass(frozen=True)
class DocumentSemanticProfile:
    document_id: str
    content_hash: str
    char_count: int
    line_count: int
    recognized_domains: list[str]
    domain_hit_count: int
    design_marker_score: float
    evidence_line_count: int
    user_story_reference_count: int
    object_candidates: list[SemanticObjectCandidate]
    parse_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DslApplicabilityMetrics:
    score: float
    domain_score: float
    structure_score: float
    evidence_coverage_score: float
    object_signal_score: float
    version_risk_count: int
    evidence_gap_count: int
    type_issue_count: int
    object_risk_count: int
    high_risk_object_count: int
    recommended_decision: RouteDecision
    reasons: list[str] = field(default_factory=list)
    object_risks: list[ObjectRiskSummary] = field(default_factory=list)


@dataclass(frozen=True)
class ChainWritePlan:
    chain_name: str
    enabled: bool
    would_execute_write: bool = False
    target_workspace: str | None = None
    target_namespace: str | None = None
    planned_operations: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass(frozen=True)
class ShadowRoutePlan:
    request: UnifiedIngestionRequest
    profile: DocumentSemanticProfile
    metrics: DslApplicabilityMetrics
    requested_mode: IngestionRequestMode
    live_route: RouteDecision
    shadow_candidate_route: RouteDecision | None
    selected_plan_route: RouteDecision
    raw_text_plan: ChainWritePlan
    dsl_plan: ChainWritePlan
    generic_graph_fallback_plan: ChainWritePlan
    parse_failed: bool
    safety_invariants: dict[str, bool]
    notes: list[str] = field(default_factory=list)


class DslAwareIngestionOrchestrator:
    def __init__(
        self,
        options: IngestionProtocolOptions | None = None,
        registry=None,
    ) -> None:
        self.options = options or IngestionProtocolOptions()
        self.registry = registry or default_domain_registry()

    def build_plan(self, request: UnifiedIngestionRequest) -> ShadowRoutePlan:
        if request.mode not in {"raw", "dsl", "auto", "shadow"}:
            raise ValueError(f"Unsupported ingestion mode: {request.mode}")
        profile = build_document_semantic_profile(request, self.registry)
        metrics = assess_dsl_applicability(profile, request, self.options)
        parse_failed = bool(profile.parse_errors)
        live_route, shadow_candidate, selected = self._select_routes(
            request.mode, metrics.recommended_decision, parse_failed
        )
        return ShadowRoutePlan(
            request=request,
            profile=profile,
            metrics=metrics,
            requested_mode=request.mode,
            live_route=live_route,
            shadow_candidate_route=shadow_candidate,
            selected_plan_route=selected,
            raw_text_plan=_raw_plan(request, live_route),
            dsl_plan=_dsl_plan(selected, metrics),
            generic_graph_fallback_plan=_generic_graph_plan(request, selected),
            parse_failed=parse_failed,
            safety_invariants=safety_invariants(),
            notes=_plan_notes(request, metrics, live_route, shadow_candidate, selected),
        )

    def _select_routes(
        self,
        mode: IngestionRequestMode,
        recommended: RouteDecision,
        parse_failed: bool,
    ) -> tuple[RouteDecision, RouteDecision | None, RouteDecision]:
        if parse_failed:
            return "PARSE_FAILED", None if mode != "shadow" else "PARSE_FAILED", "PARSE_FAILED"
        if mode == "raw":
            return "RAW_ONLY", None, "RAW_ONLY"
        if mode == "dsl":
            return recommended, None, recommended
        if mode == "auto":
            selected = recommended if recommended in {"DSL_FULL", "DSL_PARTIAL"} else "RAW_ONLY"
            return selected, None, selected
        shadow_candidate = recommended if recommended in {"DSL_FULL", "DSL_PARTIAL"} else "RAW_ONLY"
        return "RAW_ONLY", shadow_candidate, shadow_candidate


def build_document_semantic_profile(request: UnifiedIngestionRequest, registry=None) -> DocumentSemanticProfile:
    registry = registry or default_domain_registry()
    content = request.content or ""
    stripped = content.strip()
    parse_errors = []
    if not stripped:
        parse_errors.append("empty_document")
    if "\x00" in content:
        parse_errors.append("binary_like_content")
    lines = [line for line in content.splitlines() if line.strip()]
    lower = content.lower()
    recognized_domains = _recognized_domains(lower, request.metadata, registry)
    evidence_lines = _evidence_line_numbers(lines)
    objects = _object_candidates(lines, evidence_lines)
    return DocumentSemanticProfile(
        document_id=request.document_id,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
        char_count=len(content),
        line_count=len(lines),
        recognized_domains=recognized_domains,
        domain_hit_count=len(recognized_domains),
        design_marker_score=_design_marker_score(lines),
        evidence_line_count=len(evidence_lines),
        user_story_reference_count=len(US_PATTERN.findall(content)),
        object_candidates=objects,
        parse_errors=parse_errors,
    )


def assess_dsl_applicability(
    profile: DocumentSemanticProfile,
    request: UnifiedIngestionRequest,
    options: IngestionProtocolOptions | None = None,
) -> DslApplicabilityMetrics:
    options = options or IngestionProtocolOptions()
    if profile.parse_errors:
        return DslApplicabilityMetrics(
            score=0.0,
            domain_score=0.0,
            structure_score=0.0,
            evidence_coverage_score=0.0,
            object_signal_score=0.0,
            version_risk_count=0,
            evidence_gap_count=0,
            type_issue_count=0,
            object_risk_count=0,
            high_risk_object_count=0,
            recommended_decision="PARSE_FAILED",
            reasons=profile.parse_errors,
        )
    risks = _object_risks(profile, request)
    version_risk_count = sum(1 for risk in risks if risk.risk_category == "version")
    evidence_gap_count = sum(1 for risk in risks if risk.risk_category == "evidence")
    type_issue_count = sum(1 for risk in risks if risk.risk_category == "type")
    high_risk_object_count = sum(1 for risk in risks if risk.severity == "high")
    domain_score = min(1.0, profile.domain_hit_count / 2)
    structure_score = min(1.0, profile.design_marker_score / 5)
    evidence_coverage_score = min(1.0, profile.evidence_line_count / max(1, len(profile.object_candidates)))
    object_signal_score = min(1.0, len(profile.object_candidates) / 3)
    risk_penalty = min(0.45, (high_risk_object_count * 0.12) + (len(risks) * 0.04))
    score = max(
        0.0,
        round(
            (domain_score * 0.20)
            + (structure_score * 0.35)
            + (evidence_coverage_score * 0.25)
            + (object_signal_score * 0.20)
            - risk_penalty,
            4,
        ),
    )
    reasons = _metric_reasons(
        profile,
        score,
        domain_score,
        structure_score,
        evidence_coverage_score,
        object_signal_score,
        risks,
    )
    recommended = _recommend_decision(score, evidence_coverage_score, high_risk_object_count, profile, options)
    return DslApplicabilityMetrics(
        score=score,
        domain_score=round(domain_score, 4),
        structure_score=round(structure_score, 4),
        evidence_coverage_score=round(evidence_coverage_score, 4),
        object_signal_score=round(object_signal_score, 4),
        version_risk_count=version_risk_count,
        evidence_gap_count=evidence_gap_count,
        type_issue_count=type_issue_count,
        object_risk_count=len(risks),
        high_risk_object_count=high_risk_object_count,
        recommended_decision=recommended,
        reasons=reasons,
        object_risks=risks,
    )


def safety_invariants() -> dict[str, bool]:
    return {
        "LIVE_UPLOAD_BEHAVIOR_CHANGED": False,
        "LIVE_SHADOW_HOOK_CONNECTED": False,
        "AUTO_WRITE_ROUTING_ENABLED": False,
        "RAW_WRITE_EXECUTED": False,
        "DSL_WRITE_EXECUTED": False,
        "NETWORK_CALLS_EXECUTED": False,
        "MODEL_CALLS_EXECUTED": False,
        "STORAGE_WRITES_EXECUTED": False,
        "LIGHTRAG_CORE_MODIFIED": False,
    }


def serialize_plan(plan: ShadowRoutePlan) -> dict[str, Any]:
    return asdict(plan)


def serialize_protocol_report(plans: list[ShadowRoutePlan]) -> dict[str, Any]:
    invariants = safety_invariants()
    return {
        "protocol_version": "24B-0",
        "plan_count": len(plans),
        "route_distribution": _route_distribution(plans),
        "safety_invariants": invariants,
        "plans": [serialize_plan(plan) for plan in plans],
    }


def _recognized_domains(lower: str, metadata: dict[str, Any], registry) -> list[str]:
    candidates: set[str] = set()
    domain_metadata = metadata.get("domain") or metadata.get("domain_code")
    if domain_metadata:
        normalized = registry.normalize_domain(str(domain_metadata))
        if normalized != DOMAIN_OTHER:
            candidates.add(normalized)
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(keyword in lower for keyword in keywords):
            candidates.add(domain)
    for domain in registry.all_domain_codes():
        if domain.lower() in lower and domain != DOMAIN_OTHER:
            candidates.add(domain)
    return sorted(candidates)


def _evidence_line_numbers(lines: list[str]) -> list[int]:
    evidence = []
    for index, line in enumerate(lines, start=1):
        lower = line.lower()
        stripped = lower.strip()
        if (
            stripped.startswith(("evidence:", "source:", "acceptance criteria:"))
            or US_PATTERN.search(line)
            or " text unit " in lower
        ):
            evidence.append(index)
    return evidence


def _object_candidates(lines: list[str], evidence_lines: list[int]) -> list[SemanticObjectCandidate]:
    found: dict[str, SemanticObjectCandidate] = {}
    evidence_set = set(evidence_lines)
    for index, line in enumerate(lines, start=1):
        for match in OBJECT_PATTERN.findall(line):
            label = match.strip().strip(":")
            label_lower = label.lower()
            if len(label) < 4 or label_lower in STOP_OBJECT_LABELS:
                continue
            for prefix in ("Given ", "When ", "Then ", "Entity ", "Relationship "):
                if label.startswith(prefix):
                    label = label.removeprefix(prefix).strip()
                    label_lower = label.lower()
            if len(label) < 4 or label_lower in STOP_OBJECT_LABELS:
                continue
            object_id = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            if not object_id:
                continue
            prior = found.get(object_id)
            evidence = list(prior.evidence_line_numbers) if prior else []
            if index in evidence_set and index not in evidence:
                evidence.append(index)
            found[object_id] = SemanticObjectCandidate(
                object_id=object_id,
                label=label,
                inferred_type=_infer_type(label, line),
                evidence_line_numbers=evidence,
                risk_categories=list(prior.risk_categories) if prior else [],
            )
    return list(found.values())[:50]


def _infer_type(label: str, line: str) -> str:
    lower = f"{label} {line}".lower()
    if "version" in lower:
        return "RuleVersion"
    if "field" in lower or "status" in lower or "condition" in lower:
        return "FieldSpec"
    if "rule" in lower:
        return "RuleAtom"
    if "user story" in lower or US_PATTERN.search(line):
        return "UserStory"
    return "DomainObject"


def _design_marker_score(lines: list[str]) -> float:
    score = 0.0
    for line in lines:
        lower = line.strip().lower()
        if not lower:
            continue
        for marker, weight in DESIGN_MARKERS.items():
            if lower.startswith(f"{marker}:") or lower == marker or (
                marker in {"given", "when", "then"} and lower.startswith(marker + " ")
            ):
                score += weight
                break
    return score


def _object_risks(profile: DocumentSemanticProfile, request: UnifiedIngestionRequest) -> list[ObjectRiskSummary]:
    content_lower = request.content.lower()
    risks: list[ObjectRiskSummary] = []
    if profile.evidence_line_count == 0 and profile.object_candidates:
        risks.append(
            ObjectRiskSummary(
                object_id="document_evidence",
                label="Document Evidence",
                risk_category="evidence",
                severity="medium",
                reason="document has object/domain signals but no evidence/source/US marker",
            )
        )
    if any(term in content_lower for term in VERSION_TERMS):
        risks.append(
            ObjectRiskSummary(
                object_id="document_version_policy",
                label="Document Version Policy",
                risk_category="version",
                severity="high",
                reason="version/supersedes/deprecation language requires explicit policy review",
            )
        )
    for term in TYPE_RISK_TERMS:
        if term in content_lower:
            risks.append(
                ObjectRiskSummary(
                    object_id=f"type_issue_{term.replace(' ', '_')}",
                    label=term,
                    risk_category="type",
                    severity="medium",
                    reason="ambiguous type term found in source text",
                )
            )
    if not profile.recognized_domains:
        risks.append(
            ObjectRiskSummary(
                object_id="document_domain",
                label="Document Domain",
                risk_category="domain",
                severity="medium",
                reason="no supported DSL domain signal was detected",
            )
        )
    if profile.design_marker_score < 1.0:
        risks.append(
            ObjectRiskSummary(
                object_id="document_structure",
                label="Document Structure",
                risk_category="structure",
                severity="medium",
                reason="document lacks product-design structure markers",
            )
        )
    return risks


def _recommend_decision(
    score: float,
    evidence_coverage_score: float,
    high_risk_object_count: int,
    profile: DocumentSemanticProfile,
    options: IngestionProtocolOptions,
) -> RouteDecision:
    if score >= options.min_full_score and evidence_coverage_score >= options.min_evidence_coverage_for_full and high_risk_object_count <= options.max_high_risk_objects_for_full:
        return "DSL_FULL"
    if score >= options.min_partial_score and (profile.domain_hit_count > 0 or profile.design_marker_score > 0):
        return "DSL_PARTIAL"
    return "RAW_ONLY"


def _metric_reasons(
    profile: DocumentSemanticProfile,
    score: float,
    domain_score: float,
    structure_score: float,
    evidence_coverage_score: float,
    object_signal_score: float,
    risks: list[ObjectRiskSummary],
) -> list[str]:
    reasons = [
        f"score={score}",
        f"domain_score={round(domain_score, 4)} domains={profile.recognized_domains}",
        f"structure_score={round(structure_score, 4)} marker_score={profile.design_marker_score}",
        f"evidence_coverage_score={round(evidence_coverage_score, 4)} evidence_lines={profile.evidence_line_count}",
        f"object_signal_score={round(object_signal_score, 4)} object_count={len(profile.object_candidates)}",
    ]
    if risks:
        risk_counts: dict[str, int] = {}
        for risk in risks:
            risk_counts[risk.risk_category] = risk_counts.get(risk.risk_category, 0) + 1
        reasons.append(f"object_risk_distribution={risk_counts}")
    return reasons


def _raw_plan(request: UnifiedIngestionRequest, live_route: RouteDecision) -> ChainWritePlan:
    return ChainWritePlan(
        chain_name="original_raw_text_chain",
        enabled=True,
        would_execute_write=False,
        target_workspace=None,
        target_namespace=None,
        planned_operations=["preserve_original_text", "plan_full_docs_doc_status_text_chunks"],
        reason=f"raw evidence chain is retained for mode={request.mode}; live_route={live_route}",
    )


def _dsl_plan(selected: RouteDecision, metrics: DslApplicabilityMetrics) -> ChainWritePlan:
    enabled = selected in {"DSL_FULL", "DSL_PARTIAL"}
    return ChainWritePlan(
        chain_name="dsl_custom_kg_chain",
        enabled=enabled,
        would_execute_write=False,
        target_workspace=None,
        target_namespace=None,
        planned_operations=["compile_controlled_semantics", "plan_custom_kg"] if enabled else [],
        reason=f"selected_route={selected}; score={metrics.score}; no ainsert_custom_kg is called in 24B-0",
    )


def _generic_graph_plan(request: UnifiedIngestionRequest, selected: RouteDecision) -> ChainWritePlan:
    enabled = bool(request.allow_generic_graph_fallback and selected in {"RAW_ONLY", "DSL_PARTIAL"})
    return ChainWritePlan(
        chain_name="native_generic_graph_fallback",
        enabled=enabled,
        would_execute_write=False,
        target_workspace=None,
        target_namespace=None,
        planned_operations=["plan_native_extract_entities_fallback"] if enabled else [],
        reason=(
            "generic graph fallback is explicitly enabled but only planned, not written"
            if enabled
            else "generic graph fallback disabled or not applicable"
        ),
    )


def _plan_notes(
    request: UnifiedIngestionRequest,
    metrics: DslApplicabilityMetrics,
    live_route: RouteDecision,
    shadow_candidate: RouteDecision | None,
    selected: RouteDecision,
) -> list[str]:
    notes = [
        "24B-0 produces a plan only; no LightRAG write APIs are invoked.",
        "Original text evidence chain is always retained in the plan.",
        "Domain hit alone is insufficient; structure, evidence, object signals, and risk counts affect DSL applicability.",
        f"mode={request.mode} live_route={live_route} selected_plan_route={selected}",
    ]
    if request.mode == "shadow":
        notes.append(f"shadow_candidate_route={shadow_candidate}; live upload behavior remains raw-only/not connected.")
    if metrics.recommended_decision == "DSL_PARTIAL":
        notes.append("DSL_PARTIAL requires review before write routing is enabled in a later block.")
    return notes


def _route_distribution(plans: list[ShadowRoutePlan]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for plan in plans:
        distribution[plan.selected_plan_route] = distribution.get(plan.selected_plan_route, 0) + 1
    return distribution
