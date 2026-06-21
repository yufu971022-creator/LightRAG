from __future__ import annotations

from .design_quality_types import ImpactAnalysisResult, ImpactItem, QualityGateResult, SourceCitation


def build_impact_analysis_result(
    *,
    requirement: str,
    scenario: str,
    primary_change_targets: list[str],
    direct_impacts: list[ImpactItem],
    indirect_impacts: list[ImpactItem],
    tentative_impacts: list[ImpactItem],
    excluded_candidates: list[ImpactItem],
    source_citations: list[SourceCitation],
    domain_coverage: dict[str, object] | None = None,
    feature_coverage: dict[str, object] | None = None,
    version_context: dict[str, object] | None = None,
    issues_and_warnings: list[dict[str, object]] | None = None,
    open_questions: list[dict[str, str]] | None = None,
    test_scope_hints: list[str] | None = None,
    safe_for_business_use: bool = True,
) -> ImpactAnalysisResult:
    return ImpactAnalysisResult(
        requirement=requirement,
        scenario=scenario,
        primary_change_targets=primary_change_targets,
        direct_impacts=direct_impacts,
        indirect_impacts=indirect_impacts,
        tentative_impacts=tentative_impacts,
        excluded_candidates=excluded_candidates,
        domain_coverage=domain_coverage or {"relevant_domains": [], "required_dimensions": [], "not_applicable_dimensions": []},
        feature_coverage=feature_coverage or {"covered_features": []},
        version_context=version_context or {"resolution_status": "CONFIRMED_CURRENT", "version_warnings": []},
        source_citations=source_citations,
        issues_and_warnings=issues_and_warnings or [],
        open_questions=open_questions or [],
        test_scope_hints=test_scope_hints or [],
        safe_for_business_use=safe_for_business_use,
        quality_gate_result=None,
        execution_trace=[{"skill": "IMPACT_ANALYSIS", "executed": True, "mode": "DETERMINISTIC_OFFLINE"}],
    )


def validate_impact_analysis_contract(result: ImpactAnalysisResult) -> QualityGateResult:
    errors: list[str] = []
    if not result.execution_trace:
        errors.append("MISSING_EXECUTION_TRACE")
    if not result.primary_change_targets and result.scenario != "ZERO_TO_ONE":
        errors.append("MISSING_PRIMARY_CHANGE_TARGET")
    if not result.source_citations and result.scenario != "ZERO_TO_ONE":
        errors.append("MISSING_CITATION")
    return QualityGateResult("IMPACT_ANALYSIS_CONTRACT", not errors, errors, {"impact_count": _impact_count(result)})


def _impact_count(result: ImpactAnalysisResult) -> int:
    return len(result.direct_impacts) + len(result.indirect_impacts) + len(result.tentative_impacts)
