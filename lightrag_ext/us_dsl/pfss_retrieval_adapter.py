from __future__ import annotations

from .hybrid_retrieval_types import HybridRetrievalRequest, QuerySemanticProfile, RetrievalCandidate

PFSS_CHANNELS = {"PFSS_ENTITY", "PFSS_RELATION", "PFSS_PATH"}


class PfssRetrievalAdapter:
    def __init__(self, candidates: list[RetrievalCandidate]) -> None:
        self._candidates = list(candidates)

    def search(
        self,
        request: HybridRetrievalRequest,
        profile: QuerySemanticProfile,
    ) -> list[RetrievalCandidate]:
        del profile
        results = [
            candidate
            for candidate in self._candidates
            if candidate.channel in PFSS_CHANNELS
            and not candidate.deleted
            and (request.include_historical or candidate.active)
            and not _scope_excluded(candidate, request)
        ]
        return sorted(results, key=lambda item: (-item.raw_score, item.candidate_id))[: request.top_k]


def _scope_excluded(candidate: RetrievalCandidate, request: HybridRetrievalRequest) -> bool:
    if not request.strict_scope:
        return False
    return any(
        [
            bool(request.domain_code and candidate.domain_code != request.domain_code),
            bool(request.feature_key and candidate.feature_key != request.feature_key),
            bool(request.object_type and candidate.object_type != request.object_type),
        ]
    )
