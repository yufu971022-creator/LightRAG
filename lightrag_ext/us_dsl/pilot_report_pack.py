from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .candidate_extraction import CandidateExtractionReport
from .candidate_review_report import (
    CandidateReviewReport,
    DECISION_AUTO_ACCEPT,
    DECISION_INFO_ONLY,
    serialize_candidate_review_report,
)
from .candidate_types import (
    CandidateEntity,
    CandidateRelation,
)
from .generalization_audit import GeneralizationAuditReport, run_generalization_audit
from .payload_types import DslAwareIngestionPayload
from .pilot_report_types import PilotReadiness, PilotReportPack
from .source_text_unit_builder import stable_hash


def build_pilot_report_pack(
    *,
    ingestion_payload: DslAwareIngestionPayload,
    candidate_extraction_report: CandidateExtractionReport,
    candidate_review_report: CandidateReviewReport,
    module_name: str | None = None,
    source_file: str | None = None,
    generalization_audit_report: GeneralizationAuditReport | None = None,
) -> PilotReportPack:
    audit = generalization_audit_report or run_generalization_audit()
    candidates: list[CandidateEntity | CandidateRelation] = [
        *candidate_extraction_report.candidate_entities,
        *candidate_extraction_report.candidate_relations,
    ]
    decision_by_id = _decision_summary_by_id(candidate_review_report)
    evidence_summary = _evidence_summary(candidates)
    review_serialized = serialize_candidate_review_report(candidate_review_report)
    report = PilotReportPack(
        report_id=_report_id(ingestion_payload.document_id),
        generated_at=datetime.now(timezone.utc).isoformat(),
        module_name=module_name,
        document_id=ingestion_payload.document_id,
        source_file=source_file,
        dsl_version=ingestion_payload.dsl_version,
        active_domains=list(ingestion_payload.summary.get("activeDomains") or []),
        section_type_distribution=dict(
            Counter(item.section_type for item in ingestion_payload.metadata_payload)
        ),
        feature_count=len(
            {
                item.feature_key
                for item in ingestion_payload.metadata_payload
                if item.feature_key
            }
        ),
        source_us_count=len(
            {
                item.source_us_id
                for item in ingestion_payload.metadata_payload
                if item.source_us_id
            }
        ),
        source_text_unit_count=ingestion_payload.source_text_unit_count,
        dsl_aware_chunk_count=ingestion_payload.dsl_aware_chunk_count,
        vector_payload_count=len(ingestion_payload.vector_payload),
        extraction_payload_count=len(ingestion_payload.extraction_payload),
        candidate_entity_count=candidate_extraction_report.candidate_entity_count,
        candidate_relation_count=candidate_extraction_report.candidate_relation_count,
        review_summary={
            "totalCandidates": candidate_review_report.total_candidates,
            "autoAcceptCount": candidate_review_report.auto_accept_count,
            "autoResolveCount": candidate_review_report.auto_resolve_count,
            "infoOnlyCount": candidate_review_report.info_only_count,
            "reviewRequiredCount": candidate_review_report.review_required_count,
            "blockedCount": candidate_review_report.blocked_count,
            "humanReviewRatio": candidate_review_report.human_review_ratio,
        },
        version_summary={
            "versionReviewRequiredCount": candidate_review_report.version_review_required_count,
            "items": _review_items_by_flag(review_serialized, "version_review_required"),
        },
        term_summary={
            "termReviewRequiredCount": candidate_review_report.term_review_required_count,
            "items": _review_items_by_flag(review_serialized, "term_review_required"),
        },
        evidence_summary=evidence_summary,
        auto_accept_section=_candidate_section(
            candidates,
            decision_by_id,
            decision=DECISION_AUTO_ACCEPT,
        ),
        info_only_section=_candidate_section(
            candidates,
            decision_by_id,
            decision=DECISION_INFO_ONLY,
            extra_note="Info-only item. not a formal fact, no graph write, no manual review required.",
        ),
        review_required_section=[
            _decision_item(decision)
            for decision in candidate_review_report.review_required_items
        ],
        blocked_section=[
            _decision_item(decision) for decision in candidate_review_report.blocked_items
        ],
        feature_summary=candidate_review_report.grouped_by_feature,
        domain_summary=candidate_review_report.grouped_by_domain,
        generalization_audit_summary=_audit_summary(audit),
        pilot_readiness=PilotReadiness(status="", reasons=[]),
        risks=[*candidate_review_report.risks],
        recommendations=[*candidate_review_report.recommendations],
        next_step="",
    )
    report.pilot_readiness = evaluate_pilot_readiness(report)
    report.next_step = report.pilot_readiness.status
    _append_pack_risks_and_recommendations(report)
    return report


def evaluate_pilot_readiness(report: PilotReportPack) -> PilotReadiness:
    reasons: list[str] = []
    if report.generalization_audit_summary.get("productionHardcodeCount", 0) > 0:
        return PilotReadiness(
            status="NOT_READY_HARDCODE_RISK",
            reasons=["Production hardcode findings must be removed before pilot."],
        )
    if report.review_summary.get("humanReviewRatio", 0.0) > 0.30:
        return PilotReadiness(
            status="NOT_READY_REVIEW_BURDEN_HIGH",
            reasons=["Human review ratio is above 0.30."],
        )
    if report.evidence_summary.get("evidenceMissingRatio", 0.0) > 0.05:
        return PilotReadiness(
            status="NOT_READY_EVIDENCE_RISK",
            reasons=["Evidence missing ratio is above 0.05."],
        )
    if report.review_summary.get("blockedCount", 0) > 0:
        return PilotReadiness(
            status="NOT_READY_EVIDENCE_RISK",
            reasons=["Blocked candidates remain in the report."],
        )
    if report.review_summary.get("humanReviewRatio", 0.0) <= 0.20:
        reasons.append("Review burden is low enough for report-only internal pilot.")
        reasons.append("No graph write or automatic promotion is allowed.")
        return PilotReadiness(status="READY_FOR_INTERNAL_PILOT", reasons=reasons)
    reasons.append("Small review queue exists; restrict to BA/SE report-only review.")
    return PilotReadiness(status="READY_FOR_LIMITED_BA_SE_REVIEW", reasons=reasons)


def serialize_pilot_report_pack(report: PilotReportPack) -> dict[str, Any]:
    return {
        **asdict(report),
        "pilot_readiness": asdict(report.pilot_readiness),
    }


def render_pilot_report_markdown(report: PilotReportPack) -> str:
    return "\n".join(
        [
            "# Pilot Report Pack",
            "",
            "## 1. Summary",
            f"- Document: {report.document_id or 'unknown'}",
            f"- Module: {report.module_name or 'unspecified'}",
            f"- Candidates: {report.review_summary['totalCandidates']}",
            f"- Human review ratio: {report.review_summary['humanReviewRatio']:.2%}",
            "",
            "## 2. Scope and Guardrails",
            "- Report-only candidate context.",
            "- No graph write.",
            "- No formal store write.",
            "- No automatic promotion.",
            "- Auto-accepted items remain candidates, not formal facts.",
            "",
            "## 3. Source Coverage",
            f"- Source US count: {report.source_us_count}",
            f"- Source text unit count: {report.source_text_unit_count}",
            f"- Vector payload count: {report.vector_payload_count}",
            f"- Extraction payload count: {report.extraction_payload_count}",
            "",
            "## 4. Domain / Feature Coverage",
            f"- Active domains: {', '.join(report.active_domains) or 'none'}",
            f"- Feature count: {report.feature_count}",
            f"- Section types: {report.section_type_distribution}",
            "",
            "## 5. Auto-accepted Candidate Summary",
            _section_count_line(report.auto_accept_section),
            "",
            "## 6. Info-only Candidate Summary",
            "- Info-only items are not formal facts, not graph writes, and require no manual review.",
            _section_count_line(report.info_only_section),
            "",
            "## 7. Review-required Items",
            _review_lines(report.review_required_section),
            "",
            "## 8. Version Review Items",
            _summary_count_line(report.version_summary, "versionReviewRequiredCount"),
            "",
            "## 9. Term Review Items",
            _summary_count_line(report.term_summary, "termReviewRequiredCount"),
            "",
            "## 10. Evidence Samples",
            f"- Evidence-ready candidates: {report.evidence_summary['evidenceReadyCount']}",
            f"- Missing evidence candidates: {report.evidence_summary['missingEvidenceCount']}",
            "",
            "## 11. Generalization / Hardcode Audit",
            f"- Pass status: {report.generalization_audit_summary['passStatus']}",
            f"- Production hardcodes: {report.generalization_audit_summary['productionHardcodeCount']}",
            "- This report pack is module-agnostic; add new module fixtures and registry config for new pilots.",
            "",
            "## 12. Pilot Readiness",
            f"- Status: {report.pilot_readiness.status}",
            *[f"- {reason}" for reason in report.pilot_readiness.reasons],
            "",
            "## 13. Risks and Recommendations",
            *[f"- Risk: {risk}" for risk in report.risks],
            *[f"- Recommendation: {item}" for item in report.recommendations],
        ]
    )


def _decision_summary_by_id(report: CandidateReviewReport) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for item in report.auto_items_summary:
        values[item["candidate_id"]] = dict(item)
    for decision in [*report.review_required_items, *report.blocked_items]:
        values[decision.candidate_id] = _decision_item(decision)
    return values


def _review_items_by_flag(serialized_report: dict[str, Any], flag_name: str) -> list[dict[str, Any]]:
    return [
        item
        for item in serialized_report.get("reviewRequiredItems", [])
        if item.get(flag_name) is True
    ]


def _candidate_section(
    candidates: list[CandidateEntity | CandidateRelation],
    decision_by_id: dict[str, dict[str, Any]],
    *,
    decision: str,
    extra_note: str | None = None,
) -> list[dict[str, Any]]:
    section: list[dict[str, Any]] = []
    for candidate in candidates:
        decision_info = decision_by_id.get(candidate.candidate_id)
        if not decision_info or decision_info.get("decision") != decision:
            continue
        section.append(
            {
                "candidateId": candidate.candidate_id,
                "candidateType": "entity" if isinstance(candidate, CandidateEntity) else "relation",
                "name": _candidate_name(candidate),
                "decision": decision,
                "reasonCode": decision_info.get("reason_code"),
                "sourceUsId": candidate.source_us_id,
                "sourceTextUnitId": candidate.source_text_unit_id,
                "sourceSpan": candidate.source_span,
                "textHash": candidate.text_hash,
                "evidenceText": candidate.evidence_text,
                "knowledgeStatus": candidate.knowledge_status,
                "note": extra_note,
            }
        )
    return section


def _decision_item(decision) -> dict[str, Any]:
    return {
        "candidateId": decision.candidate_id,
        "candidateType": decision.candidate_type,
        "decision": decision.decision,
        "reasonCode": decision.reason_code,
        "reason": decision.reason,
        "reviewPriority": decision.review_priority,
        "riskLevel": decision.risk_level,
        "sourceUsId": decision.source_us_id,
        "featureKey": decision.feature_key,
        "domainCode": decision.domain_code,
        "sectionType": decision.section_type,
        "evidenceText": decision.evidence_text,
        "suggestedReviewerQuestion": _reviewer_question(decision.reason_code),
    }


def _reviewer_question(reason_code: str) -> str:
    if reason_code == "VERSION_REVIEW_REQUIRED":
        return "Please confirm which rule is currently effective."
    if reason_code == "TERM_REVIEW_REQUIRED":
        return "Please confirm which canonical term should be used."
    if reason_code == "MISSING_EVIDENCE":
        return "Please provide or identify the source evidence."
    return "Please confirm whether this candidate should remain in the pilot report."


def _evidence_summary(candidates: list[CandidateEntity | CandidateRelation]) -> dict[str, Any]:
    total = len(candidates)
    missing = [
        candidate
        for candidate in candidates
        if not (candidate.source_text_unit_id and candidate.text_hash and candidate.evidence_text)
    ]
    return {
        "totalCandidates": total,
        "evidenceReadyCount": total - len(missing),
        "missingEvidenceCount": len(missing),
        "evidenceMissingRatio": len(missing) / total if total else 0.0,
        "sampleEvidence": [
            {
                "candidateId": candidate.candidate_id,
                "sourceUsId": candidate.source_us_id,
                "sourceTextUnitId": candidate.source_text_unit_id,
                "sourceSpan": candidate.source_span,
                "textHash": candidate.text_hash,
                "evidenceText": candidate.evidence_text,
            }
            for candidate in candidates[:5]
        ],
    }


def _audit_summary(audit: GeneralizationAuditReport) -> dict[str, Any]:
    return {
        "totalFindings": audit.total_findings,
        "productionHardcodeCount": audit.production_hardcode_count,
        "testFixtureHardcodeCount": audit.test_fixture_hardcode_count,
        "configExampleCount": audit.config_example_count,
        "ruleRegistryAllowedCount": audit.rule_registry_allowed_count,
        "unknownCount": audit.unknown_count,
        "passStatus": audit.pass_status,
        "recommendations": audit.recommendations,
    }


def _append_pack_risks_and_recommendations(report: PilotReportPack) -> None:
    if report.generalization_audit_summary["productionHardcodeCount"] > 0:
        report.risks.append("Production hardcode risk blocks pilot.")
    if report.evidence_summary["evidenceMissingRatio"] > 0.05:
        report.risks.append("Evidence missing ratio is too high for pilot.")
    report.recommendations.append("If another module fixture is absent, add it and rerun the same pilot validation.")
    report.recommendations.append("Keep pilot output report-only; do not write graph or formal store.")


def _candidate_name(candidate: CandidateEntity | CandidateRelation) -> str:
    if isinstance(candidate, CandidateEntity):
        return candidate.entity_name
    return f"{candidate.source_entity_name} -> {candidate.target_entity_name}"


def _section_count_line(section: list[dict[str, Any]]) -> str:
    return f"- Count: {len(section)}"


def _summary_count_line(summary: dict[str, Any], key: str) -> str:
    return f"- Count: {summary.get(key, 0)}"


def _review_lines(section: list[dict[str, Any]]) -> str:
    if not section:
        return "- 当前无必须人工确认项"
    return "\n".join(
        f"- {item['candidateId']}: {item['reasonCode']} - {item.get('reason')}"
        for item in section
    )


def _report_id(document_id: str | None) -> str:
    return stable_hash(document_id or "unknown", prefix="pilot")


__all__ = [
    "build_pilot_report_pack",
    "evaluate_pilot_readiness",
    "render_pilot_report_markdown",
    "serialize_pilot_report_pack",
]
