from __future__ import annotations

from .design_quality_types import DesignQualityCase, ImpactItem, SourceCitation
from .impact_analysis_contract import build_impact_analysis_result


def execute_impact_analysis(case: DesignQualityCase):
    citation = _citation(case.case_id)
    if case.scenario == "ZERO_TO_ONE":
        return build_impact_analysis_result(
            requirement=case.prompt,
            scenario=case.scenario,
            primary_change_targets=["new_capability"],
            direct_impacts=[],
            indirect_impacts=[],
            tentative_impacts=[_impact(case.case_id, citation, "TENTATIVE", "Other", "POSSIBLE", "external_constraint", review=True)],
            excluded_candidates=[],
            source_citations=[citation],
            domain_coverage={"relevant_domains": ["Other"], "required_dimensions": ["external_constraint"], "not_applicable_dimensions": []},
            safe_for_business_use=True,
        )
    if case.scenario == "ONE_TO_ONE_X":
        return build_impact_analysis_result(
            requirement=case.prompt,
            scenario=case.scenario,
            primary_change_targets=["local_target"],
            direct_impacts=[_impact(case.case_id, citation, "DIRECT", "Integration", "CONFIRMED", "field_mapping")],
            indirect_impacts=[],
            tentative_impacts=[_impact(case.case_id, citation, "TENTATIVE", "Other", "POSSIBLE", "hidden_cross_domain_risk", review=True)],
            excluded_candidates=[_impact(case.case_id, citation, "TENTATIVE", "Ledger", "UNCONFIRMED", "irrelevant_neighbor", kind="CANDIDATE", review=True)],
            source_citations=[citation],
            domain_coverage={
                "relevant_domains": ["Integration", "Other"],
                "required_dimensions": ["field_mapping"],
                "not_applicable_dimensions": ["MasterData", "Workflow", "Ledger", "RuleManagement"],
            },
            feature_coverage={"covered_features": ["local_feature"], "over_expanded": False},
        )
    return build_impact_analysis_result(
        requirement=case.prompt,
        scenario="ONE_TO_MANY",
        primary_change_targets=["primary_change_target"],
        direct_impacts=[_impact(case.case_id, citation, "DIRECT", "Workflow", "CONFIRMED", "workflow_state")],
        indirect_impacts=[_impact(case.case_id, citation, "INDIRECT", "Integration", "SUPPORTED", "interface_contract")],
        tentative_impacts=[_impact(case.case_id, citation, "TENTATIVE", "AccessAudit", "POSSIBLE", "permission_review", review=True)],
        excluded_candidates=[_impact(case.case_id, citation, "TENTATIVE", "Ledger", "UNCONFIRMED", "generic_neighbor", kind="GENERIC_ONLY", review=True)],
        source_citations=[citation],
        domain_coverage={
            "relevant_domains": ["Workflow", "Integration", "AccessAudit"],
            "required_dimensions": ["workflow_state", "interface_contract", "permission_review"],
            "optional_dimensions": ["DataMigrationInitialization"],
            "not_applicable_dimensions": ["MasterData", "Ledger", "MonitoringReport"],
        },
        feature_coverage={"covered_features": ["feature_a", "feature_b"], "over_expanded": False},
        version_context={"resolution_status": "CONFIRMED_CURRENT", "version_warnings": []},
    )


def _citation(case_id: str) -> SourceCitation:
    return SourceCitation(
        document_id=f"doc-impact-{case_id}",
        document_version_id=f"docv-impact-{case_id}",
        source_us_id=f"US-IMPACT-{case_id}",
        text_unit_id=f"tu-impact-{case_id}",
        source_span={"start": 0, "end": 80},
        text_hash=f"hash-impact-{case_id}",
        evidence_excerpt="Synthetic impact evidence excerpt for offline quality gate.",
    )


def _impact(
    case_id: str,
    citation: SourceCitation,
    level: str,
    domain: str,
    certainty: str,
    dimension: str,
    *,
    kind: str = "FACT",
    review: bool = False,
) -> ImpactItem:
    return ImpactItem(
        impact_id=f"impact-{case_id}-{level.lower()}-{domain}",
        affected_object_id=f"sem-{case_id}-{domain}",
        affected_object_name=f"{domain} object",
        affected_object_type="FUNCTIONAL_OBJECT",
        domain_code=domain,
        feature_key=f"feature-{domain.lower()}",
        impact_type=dimension,
        impact_level=level,  # type: ignore[arg-type]
        impact_path=[f"target-{case_id}", f"relation-{domain}", f"sem-{case_id}-{domain}"],
        relation_types=["AFFECTS"],
        evidence_refs=[citation.text_unit_id] if kind == "FACT" else [],
        version_status="CONFIRMED_CURRENT",
        certainty=certainty,  # type: ignore[arg-type]
        risk_level="MEDIUM" if review else "LOW",
        reason="Evidence-backed impact classification." if kind == "FACT" else "Excluded or tentative non-factual candidate.",
        requires_review=review,
        candidate_kind=kind,
    )
