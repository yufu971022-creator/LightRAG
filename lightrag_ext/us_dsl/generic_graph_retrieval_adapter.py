from __future__ import annotations

from .hybrid_retrieval_types import HybridRetrievalRequest, QuerySemanticProfile, RetrievalCandidate


class GenericGraphRetrievalAdapter:
    def __init__(self, candidates: list[RetrievalCandidate], *, enabled: bool = True) -> None:
        self._candidates = list(candidates)
        self.enabled = enabled

    def search(
        self,
        request: HybridRetrievalRequest,
        profile: QuerySemanticProfile,
    ) -> list[RetrievalCandidate]:
        del profile
        if not self.enabled or not request.include_generic:
            return []
        results = [
            candidate
            for candidate in self._candidates
            if candidate.channel == "GENERIC_GRAPH"
            and not candidate.deleted
            and (request.include_historical or candidate.active)
            and not _scope_excluded(candidate, request)
        ]
        for candidate in results:
            candidate.trust_tier = "T4_BACKGROUND"
            candidate.factual_weight = min(candidate.factual_weight, 0.2)
        return sorted(results, key=lambda item: (-item.raw_score, item.candidate_id))[: request.top_k]


def _scope_excluded(candidate: RetrievalCandidate, request: HybridRetrievalRequest) -> bool:
    if not request.strict_scope:
        return False
    if request.domain_code and candidate.domain_code != request.domain_code:
        return True
    if request.feature_key and candidate.feature_key != request.feature_key:
        return True
    return False
