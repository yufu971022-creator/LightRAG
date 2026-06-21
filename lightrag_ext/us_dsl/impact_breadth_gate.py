from __future__ import annotations

from .design_quality_types import ImpactAnalysisResult, QualityGateResult, RELEVANT_DOMAINS


def evaluate_impact_breadth(result: ImpactAnalysisResult) -> QualityGateResult:
    direct = result.direct_impacts
    indirect = result.indirect_impacts
    all_impacts = [*direct, *indirect, *result.tentative_impacts]
    duplicate_count = len(all_impacts) - len({item.affected_object_id for item in all_impacts})
    false_positive = sum(1 for item in all_impacts if item.domain_code not in RELEVANT_DOMAINS or item.candidate_kind != "FACT" and item.certainty == "CONFIRMED")
    evidence_backed = sum(1 for item in [*direct, *indirect] if item.evidence_refs)
    required_dimensions = set(result.domain_coverage.get("required_dimensions", []))
    covered_dimensions = {item.impact_type for item in all_impacts if item.candidate_kind == "FACT"}
    missing_dimensions = sorted(required_dimensions - covered_dimensions)
    evidence_ratio = 1.0 if not [*direct, *indirect] else evidence_backed / len([*direct, *indirect])
    direct_recall = 1.0 if direct else (1.0 if result.scenario == "ZERO_TO_ONE" else 0.0)
    indirect_recall = 1.0 if indirect else (1.0 if result.scenario in {"ZERO_TO_ONE", "ONE_TO_ONE_X"} else 0.0)
    coverage = 1.0 if not required_dimensions else len(covered_dimensions & required_dimensions) / len(required_dimensions)
    over_expanded = bool(result.feature_coverage.get("over_expanded")) or len(result.domain_coverage.get("relevant_domains", [])) == len(RELEVANT_DOMAINS)
    errors = []
    if not result.primary_change_targets and result.scenario != "ZERO_TO_ONE":
        errors.append("MISSING_PRIMARY_CHANGE_TARGET")
    if missing_dimensions:
        errors.append("MISSING_RELEVANT_DIMENSION")
    if duplicate_count:
        errors.append("DUPLICATE_IMPACT")
    if false_positive:
        errors.append("FALSE_POSITIVE_IMPACT")
    if over_expanded and result.scenario == "ONE_TO_ONE_X":
        errors.append("OVER_EXPANDED_DOMAIN_SCOPE")
    if evidence_ratio < 1.0:
        errors.append("UNSUPPORTED_PATH")
    return QualityGateResult(
        "IMPACT_BREADTH",
        not errors,
        errors,
        {
            "required_dimension_coverage": coverage,
            "direct_impact_recall": direct_recall,
            "indirect_impact_recall": indirect_recall,
            "evidence_backed_path_ratio": evidence_ratio,
            "false_positive_impact_count": false_positive,
            "duplicate_impact_count": duplicate_count,
            "missing_relevant_dimensions": missing_dimensions,
            "over_expanded_domain_scope": over_expanded,
        },
        errors,
    )
