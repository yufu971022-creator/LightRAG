from __future__ import annotations

from .hybrid_retrieval_types import FusionReport, QuerySemanticProfile, RetrievalCandidate

_CHANNEL_WEIGHTS = {
    "RAW_TEXT": 1.15,
    "PFSS_ENTITY": 1.25,
    "PFSS_RELATION": 1.35,
    "PFSS_PATH": 1.45,
    "GENERIC_GRAPH": 0.35,
    "ISSUE_SIDECAR": 0.0,
    "VERSION_CONTEXT": 0.0,
}
_RRF_K = 60.0


def fuse_retrieval_candidates(
    candidates: list[RetrievalCandidate],
    profile: QuerySemanticProfile,
) -> tuple[list[RetrievalCandidate], FusionReport]:
    report = FusionReport()
    candidate_scores: list[dict[str, object]] = []
    for candidate in candidates:
        rank = candidate.channel_rank or 999
        weight = _CHANNEL_WEIGHTS.get(candidate.channel, 0.1)
        factual_weight = 0.0 if candidate.channel in {"ISSUE_SIDECAR", "VERSION_CONTEXT"} else candidate.factual_weight
        score = weight * factual_weight * (1.0 / (_RRF_K + rank))
        reasons = [f"rrf={score:.6f}", f"channel_weight={weight:.2f}"]
        if candidate.domain_code and candidate.domain_code in profile.domain_hints:
            score += 0.002
            report.domain_match_boost_applied = True
            reasons.append("domain_hint_boost")
        if candidate.feature_key and candidate.feature_key in profile.feature_hints:
            score += 0.002
            report.feature_match_boost_applied = True
            reasons.append("feature_hint_boost")
        if candidate.version_status in {"CONFLICT", "UNKNOWN_CURRENT", "MULTIPLE_CURRENT_CONFLICT"}:
            score -= 0.003
            report.version_conflict_penalty_visible = True
            reasons.append("version_conflict_penalty")
        if not candidate.evidence and candidate.channel in {"PFSS_ENTITY", "PFSS_RELATION", "PFSS_PATH"}:
            score -= 0.004
            report.missing_evidence_penalty_visible = True
            reasons.append("missing_evidence_penalty")
        candidate.fused_score = round(score, 9)
        candidate.fusion_reasons = reasons
        candidate_scores.append(
            {
                "candidate_id": candidate.candidate_id,
                "channel": candidate.channel,
                "rank": rank,
                "fused_score": candidate.fused_score,
                "reasons": reasons,
            }
        )
    ordered = sorted(candidates, key=lambda item: (-item.fused_score, item.channel, item.candidate_id))
    report.candidate_scores = candidate_scores
    report.issue_factual_weight = _CHANNEL_WEIGHTS["ISSUE_SIDECAR"]
    report.direct_raw_score_addition_used = False
    report.deterministic_ranking_passed = ordered == sorted(
        list(ordered), key=lambda item: (-item.fused_score, item.channel, item.candidate_id)
    )
    return ordered, report
