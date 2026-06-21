from __future__ import annotations

from .hybrid_retrieval_types import HybridRetrievalRequest, QuerySemanticProfile, RetrievalCandidate

ISSUE_CHANNELS = {"ISSUE_SIDECAR", "VERSION_CONTEXT"}


class IssueSidecarRetrievalAdapter:
    def __init__(self, candidates: list[RetrievalCandidate]) -> None:
        self._candidates = list(candidates)

    def search(
        self,
        request: HybridRetrievalRequest,
        profile: QuerySemanticProfile,
    ) -> list[RetrievalCandidate]:
        del profile
        results: list[RetrievalCandidate] = []
        for candidate in self._candidates:
            if candidate.channel not in ISSUE_CHANNELS:
                continue
            if candidate.deleted:
                continue
            if request.strict_scope and request.domain_code and candidate.domain_code != request.domain_code:
                continue
            candidate.trust_tier = "T5_WARNING"
            candidate.factual_weight = 0.0
            results.append(candidate)
        return sorted(results, key=lambda item: (-item.raw_score, item.candidate_id))[: request.top_k]
