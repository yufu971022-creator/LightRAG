from __future__ import annotations

from .hybrid_retrieval_types import (
    EvidenceRef,
    FallbackResult,
    HybridRetrievalRequest,
    PathCandidate,
    QuerySemanticProfile,
    RetrievalCandidate,
    TokenBudgetReport,
    TrustedContextPack,
)


def build_trusted_context_pack(
    *,
    request: HybridRetrievalRequest,
    profile: QuerySemanticProfile,
    candidates: list[RetrievalCandidate],
    fallback: FallbackResult,
    max_items: int = 10,
) -> TrustedContextPack:
    factual: list[RetrievalCandidate] = []
    generic_context: list[RetrievalCandidate] = []
    issues: list[RetrievalCandidate] = []
    direct_evidence: list[EvidenceRef] = []
    factual_paths: list[PathCandidate] = []
    tentative_paths: list[PathCandidate] = []

    for candidate in candidates:
        if candidate.channel in {"ISSUE_SIDECAR", "VERSION_CONTEXT"}:
            issues.append(candidate)
            continue
        if candidate.channel == "GENERIC_GRAPH":
            generic_context.append(candidate)
            continue
        if candidate.path is not None:
            if candidate.path.validation_status == "FACTUAL":
                factual_paths.append(candidate.path)
            else:
                tentative_paths.append(candidate.path)
        if candidate.channel in {"RAW_TEXT", "PFSS_ENTITY", "PFSS_RELATION", "PFSS_PATH"}:
            factual.append(candidate)
            direct_evidence.extend(candidate.evidence)

    kept = _keep_with_required_evidence(factual, max_items=max_items)
    kept_ids = {item.candidate_id for item in kept}
    dropped = [item.candidate_id for item in factual if item.candidate_id not in kept_ids]
    factual = kept
    required_evidence_ok = all(item.evidence for item in factual if item.channel.startswith("PFSS"))
    citations = [
        {
            "document_id": item.document_id,
            "document_version_id": item.document_version_id,
            "text_unit_id": item.text_unit_id,
            "text_hash": item.text_hash,
        }
        for item in direct_evidence
    ]
    return TrustedContextPack(
        request=request,
        profile=profile,
        fallback=fallback,
        factual_candidates=factual,
        direct_evidence=direct_evidence,
        factual_paths=factual_paths,
        tentative_paths=tentative_paths,
        generic_context=generic_context,
        issue_warnings=issues,
        score_explanations=[
            {
                "candidate_id": item.candidate_id,
                "fused_score": item.fused_score,
                "reasons": list(item.fusion_reasons),
            }
            for item in candidates
        ],
        citations=citations,
        token_budget=TokenBudgetReport(
            max_items=max_items,
            kept_items=len(factual),
            token_budget_preserved_required_evidence=required_evidence_ok,
            dropped_candidate_ids=dropped,
        ),
        final_answer_generated=False,
    )


def _keep_with_required_evidence(
    candidates: list[RetrievalCandidate],
    *,
    max_items: int,
) -> list[RetrievalCandidate]:
    with_evidence = [item for item in candidates if item.evidence]
    without_evidence = [item for item in candidates if not item.evidence]
    ordered = sorted(with_evidence, key=lambda item: (-item.fused_score, item.candidate_id))
    ordered.extend(sorted(without_evidence, key=lambda item: (-item.fused_score, item.candidate_id)))
    return ordered[:max_items]
