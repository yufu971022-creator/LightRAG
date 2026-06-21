from __future__ import annotations

from .harness_types import RequirementInput, RequirementScenarioProfile

_FLOAT_FIELDS = {
    "existing_feature_coverage",
    "existing_semantic_object_coverage",
    "existing_relation_coverage",
    "existing_design_evidence_coverage",
    "existing_code_asset_coverage",
    "novelty_score",
    "new_business_object_ratio",
    "local_change_score",
    "evidence_sufficiency_score",
    "profile_confidence",
}
_INT_FIELDS = {
    "affected_feature_count",
    "affected_domain_count",
    "direct_impact_count",
    "indirect_impact_count",
    "graph_path_count",
    "version_issue_count",
    "term_issue_count",
    "type_issue_count",
    "cross_system_signal_count",
}


def build_requirement_scenario_profile(requirement: RequirementInput) -> RequirementScenarioProfile:
    metadata = dict(requirement.metadata)
    values: dict[str, object] = {}
    for field in _FLOAT_FIELDS:
        values[field] = _bounded_float(metadata.get(field, _default_float(field, requirement)))
    for field in _INT_FIELDS:
        values[field] = max(0, int(metadata.get(field, 0)))
    targets = list(metadata.get("primary_change_targets", []))
    signals = list(metadata.get("signals", []))
    risks = list(metadata.get("risks", []))
    if requirement.available_design_context:
        signals.append("design_context_available")
    if requirement.available_code_context:
        signals.append("code_context_available")
    if values["evidence_sufficiency_score"] < 0.35:
        risks.append("insufficient_evidence")
    if int(values["affected_domain_count"]) > 1:
        risks.append("cross_domain_impact")
    confidence = values["profile_confidence"]
    if confidence == 0.0:
        confidence = _infer_confidence(values)
    return RequirementScenarioProfile(
        requirement_id=requirement.requirement_id,
        primary_change_targets=targets,
        signals=sorted(set(signals)),
        risks=sorted(set(risks)),
        profile_confidence=float(confidence),
        **{key: value for key, value in values.items() if key != "profile_confidence"},
    )


def _default_float(field: str, requirement: RequirementInput) -> float:
    if field == "existing_design_evidence_coverage":
        return 0.6 if requirement.available_design_context else 0.0
    if field == "existing_code_asset_coverage":
        return 0.7 if requirement.available_code_context else 0.0
    if field == "evidence_sufficiency_score":
        return 0.55 if requirement.source_document_refs or requirement.available_design_context else 0.2
    return 0.0


def _infer_confidence(values: dict[str, object]) -> float:
    evidence = float(values.get("evidence_sufficiency_score", 0.0))
    design = float(values.get("existing_design_evidence_coverage", 0.0))
    semantic = float(values.get("existing_semantic_object_coverage", 0.0))
    return round(min(1.0, max(0.0, (evidence + design + semantic) / 3.0)), 3)


def _bounded_float(value: object) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))
