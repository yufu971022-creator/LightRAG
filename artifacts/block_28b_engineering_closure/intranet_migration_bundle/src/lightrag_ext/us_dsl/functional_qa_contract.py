from __future__ import annotations

from .design_quality_types import FunctionalQAResult, QualityGateResult, SourceCitation, SupportingFact

OUT_OF_SCOPE_SKILLS = {
    "US_GENERATION": {"capability_status": "OUT_OF_SCOPE", "executed": False},
    "AC_GENERATION": {"capability_status": "OUT_OF_SCOPE", "executed": False},
    "UX_DESIGN": {"capability_status": "OUT_OF_SCOPE", "executed": False},
    "FULL_SOLUTION_DOCUMENT_GENERATION": {"capability_status": "OUT_OF_SCOPE", "executed": False},
    "CODE_CONTEXT_HANDOFF": {"capability_status": "OUT_OF_SCOPE", "executed": False},
}


def build_functional_qa_result(
    *,
    query: str,
    scenario: str,
    answer_status: str,
    direct_answer: str,
    supporting_facts: list[SupportingFact],
    source_citations: list[SourceCitation],
    version_context: dict[str, object] | None = None,
    term_identity_context: dict[str, object] | None = None,
    supporting_relations: list[dict[str, object]] | None = None,
    supporting_paths: list[dict[str, object]] | None = None,
    issues_and_warnings: list[dict[str, object]] | None = None,
    open_questions: list[dict[str, str]] | None = None,
    excluded_claims: list[str] | None = None,
    safe_for_business_use: bool = True,
) -> FunctionalQAResult:
    return FunctionalQAResult(
        query=query,
        scenario=scenario,
        answer_status=answer_status,  # type: ignore[arg-type]
        direct_answer=direct_answer,
        supporting_facts=supporting_facts,
        supporting_relations=supporting_relations or [],
        supporting_paths=supporting_paths or [],
        source_citations=source_citations,
        version_context=version_context or {"resolution_status": "CONFIRMED_CURRENT", "version_warnings": []},
        term_identity_context=term_identity_context or {"confirmed_alias_groups": [], "candidate_aliases": []},
        issues_and_warnings=issues_and_warnings or [],
        open_questions=open_questions or [],
        excluded_claims=excluded_claims or [],
        safe_for_business_use=safe_for_business_use,
        quality_gate_result=None,
        execution_trace=[{"skill": "FUNCTIONAL_QA", "executed": True, "mode": "DETERMINISTIC_OFFLINE"}],
    )


def validate_functional_qa_contract(result: FunctionalQAResult) -> QualityGateResult:
    errors: list[str] = []
    if not result.execution_trace:
        errors.append("MISSING_EXECUTION_TRACE")
    if result.answer_status != "INSUFFICIENT_EVIDENCE" and not result.source_citations:
        errors.append("MISSING_CITATION")
    if result.answer_status == "INSUFFICIENT_EVIDENCE" and result.safe_for_business_use:
        errors.append("INSUFFICIENT_EVIDENCE_MARKED_SAFE")
    return QualityGateResult("FUNCTIONAL_QA_CONTRACT", not errors, errors, {"supporting_fact_count": len(result.supporting_facts)})
