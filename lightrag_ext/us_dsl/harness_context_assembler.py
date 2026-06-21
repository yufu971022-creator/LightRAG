from __future__ import annotations

from typing import Any

from .harness_types import HarnessContext, RequirementInput, RequirementScenarioProfile, ScenarioRouteDecision


def assemble_harness_context(
    requirement: RequirementInput,
    profile: RequirementScenarioProfile,
    route: ScenarioRouteDecision,
    *,
    trusted_context_pack: dict[str, Any] | None = None,
    version_context: dict[str, Any] | None = None,
    impact_context: dict[str, Any] | None = None,
    term_context: dict[str, Any] | None = None,
    type_context: dict[str, Any] | None = None,
    code_context: dict[str, Any] | None = None,
) -> HarnessContext:
    trusted = trusted_context_pack or _default_trusted_context(requirement)
    issues: list[dict[str, Any]] = []
    source_evidence = _extract_source_evidence(trusted, issues)
    if route.classification_status in {"AMBIGUOUS", "MIXED", "INSUFFICIENT_EVIDENCE"}:
        issues.append({"kind": "route_warning", "status": route.classification_status, "reason_codes": route.reason_codes})
    return HarnessContext(
        requirement_input=requirement,
        scenario_profile=profile,
        scenario_route=route,
        trusted_context_pack=trusted,
        version_context=version_context or {"safe_for_deterministic_answer": True, "source": "27A_offline_fixture"},
        impact_context=impact_context or {"impact_paths_available": profile.graph_path_count > 0, "source": "27A_offline_fixture"},
        term_context=term_context or {"stable_terms_available": True},
        type_context=type_context or {"entity_type_resolution_available": True},
        available_code_context=_code_context(requirement, code_context),
        source_evidence=source_evidence,
        issues_and_warnings=issues,
        assumptions=_assumptions(profile, route),
        open_questions=list(route.clarification_questions),
        context_budget={"max_items": 12, "source_evidence_count": len(source_evidence), "issue_warning_count": len(issues)},
    )


def _default_trusted_context(requirement: RequirementInput) -> dict[str, Any]:
    return {
        "source": "27A_offline_context_pack",
        "direct_evidence": [
            {
                "evidence_id": f"ev_{requirement.requirement_id}",
                "document_id": ref,
                "fact_status": "FACTUAL",
                "excerpt": "Synthetic non-sensitive evidence for harness planning.",
            }
            for ref in requirement.source_document_refs
        ],
        "factual_candidates": [],
        "issue_warnings": [],
        "candidate_aliases": [],
        "final_answer_generated": False,
    }


def _extract_source_evidence(trusted: dict[str, Any], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for item in trusted.get("direct_evidence", []):
        if item.get("fact_status") == "FACTUAL" or item.get("active", True):
            fact = dict(item)
            fact["fact_status"] = fact.get("fact_status", "FACTUAL")
            facts.append(fact)
    for item in trusted.get("factual_candidates", []):
        if item.get("fact_status") == "FACTUAL" and item.get("trust_tier") in {"T1_DIRECT", "T2_SEMANTIC"}:
            facts.append(dict(item))
        else:
            issues.append({"kind": "candidate_not_fact", "candidate_id": item.get("candidate_id"), "status": "NOT_IN_FACTS"})
    for item in trusted.get("issue_warnings", []):
        issues.append({"kind": "issue_warning", "candidate_id": item.get("candidate_id"), "status": "WARNING_NOT_FACT"})
    for alias in trusted.get("candidate_aliases", []):
        issues.append({"kind": "candidate_alias", "value": alias, "status": "CANDIDATE_NOT_FACT"})
    return facts


def _code_context(requirement: RequirementInput, code_context: dict[str, Any] | None) -> dict[str, Any]:
    if requirement.available_code_context and code_context:
        return {"status": "AVAILABLE", "source": code_context.get("source", "provided"), "details": code_context}
    return {"status": "UNAVAILABLE", "source": "not_configured", "details": {}}


def _assumptions(profile: RequirementScenarioProfile, route: ScenarioRouteDecision) -> list[str]:
    assumptions: list[str] = []
    if route.selected_scenario == "ZERO_TO_ONE":
        assumptions.append("Novelty requires human confirmation before final design output.")
    if profile.version_issue_count > 0:
        assumptions.append("Version issues require explicit review before final output.")
    return assumptions
