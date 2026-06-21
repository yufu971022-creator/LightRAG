from __future__ import annotations

from .hybrid_retrieval_types import HybridRetrievalRequest, QuerySemanticProfile, RetrievalCandidate


class RawTextRetrievalAdapter:
    def __init__(self, candidates: list[RetrievalCandidate]) -> None:
        self._candidates = list(candidates)

    def search(
        self,
        request: HybridRetrievalRequest,
        profile: QuerySemanticProfile,
    ) -> list[RetrievalCandidate]:
        del profile
        results: list[RetrievalCandidate] = []
        seen: set[tuple[str | None, str | None, tuple[tuple[str, int], ...]]] = set()
        for candidate in self._candidates:
            if candidate.channel != "RAW_TEXT":
                continue
            if candidate.deleted:
                continue
            if not request.include_historical and not candidate.active:
                continue
            if _scope_excluded(candidate, request):
                continue
            if "<DSL_CONTEXT>" in candidate.text:
                continue
            evidence = candidate.evidence[0] if candidate.evidence else None
            span = tuple(sorted((evidence.source_span if evidence else {}).items()))
            key = (
                evidence.document_version_id if evidence else None,
                evidence.text_hash if evidence else candidate.candidate_id,
                span,
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(candidate)
        return sorted(results, key=lambda item: (-item.raw_score, item.candidate_id))[: request.top_k]


def _scope_excluded(candidate: RetrievalCandidate, request: HybridRetrievalRequest) -> bool:
    if not request.strict_scope:
        return False
    if request.domain_code and candidate.domain_code != request.domain_code:
        return True
    if request.feature_key and candidate.feature_key != request.feature_key:
        return True
    if request.object_type and candidate.object_type != request.object_type:
        return True
    return False
