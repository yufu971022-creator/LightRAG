from __future__ import annotations

from dataclasses import dataclass, field

from .evidence_path_validator import validate_evidence_paths
from .generic_graph_retrieval_adapter import GenericGraphRetrievalAdapter
from .hybrid_retrieval_fallback import decide_hybrid_retrieval_fallback
from .hybrid_retrieval_types import HybridRetrievalRequest, HybridRetrievalResult, RetrievalCandidate
from .issue_sidecar_retrieval_adapter import IssueSidecarRetrievalAdapter
from .pfss_retrieval_adapter import PfssRetrievalAdapter
from .query_semantic_profile import build_query_semantic_profile
from .raw_text_retrieval_adapter import RawTextRetrievalAdapter
from .retrieval_candidate_deduplicator import deduplicate_retrieval_candidates
from .retrieval_candidate_normalizer import normalize_retrieval_candidates
from .trusted_context_builder import build_trusted_context_pack
from .trust_aware_rank_fusion import fuse_retrieval_candidates


@dataclass
class InMemoryHybridRetrievalStore:
    raw_candidates: list[RetrievalCandidate] = field(default_factory=list)
    pfss_candidates: list[RetrievalCandidate] = field(default_factory=list)
    generic_candidates: list[RetrievalCandidate] = field(default_factory=list)
    issue_candidates: list[RetrievalCandidate] = field(default_factory=list)


class HybridRetrievalService:
    def __init__(self, store: InMemoryHybridRetrievalStore, *, term_registry: object | None = None) -> None:
        self.store = store
        self.term_registry = term_registry

    def retrieve(self, request: HybridRetrievalRequest) -> HybridRetrievalResult:
        profile = build_query_semantic_profile(request, term_registry=self.term_registry)
        raw_candidates = RawTextRetrievalAdapter(self.store.raw_candidates).search(request, profile)
        pfss_candidates = PfssRetrievalAdapter(self.store.pfss_candidates).search(request, profile)
        generic_candidates = GenericGraphRetrievalAdapter(self.store.generic_candidates).search(request, profile)
        issue_candidates = IssueSidecarRetrievalAdapter(self.store.issue_candidates).search(request, profile)
        all_candidates = raw_candidates + pfss_candidates + generic_candidates + issue_candidates
        normalized, normalization_report = normalize_retrieval_candidates(all_candidates)
        deduplicated, deduplication_report = deduplicate_retrieval_candidates(normalized)
        paths = [candidate.path for candidate in deduplicated if candidate.path is not None]
        path_report = validate_evidence_paths(paths, task_type=request.task_type, max_hops=request.max_hops)
        fused, fusion_report = fuse_retrieval_candidates(deduplicated, profile)
        fallback = decide_hybrid_retrieval_fallback(
            fused,
            strict_scope=request.strict_scope,
            path_report=path_report,
        )
        context_pack = build_trusted_context_pack(
            request=request,
            profile=profile,
            candidates=fused,
            fallback=fallback,
        )
        return HybridRetrievalResult(
            request=request,
            profile=profile,
            raw_candidates=raw_candidates,
            pfss_candidates=pfss_candidates,
            generic_candidates=generic_candidates,
            issue_candidates=issue_candidates,
            normalized_candidates=normalized,
            deduplicated_candidates=deduplicated,
            fused_candidates=fused,
            fallback=fallback,
            context_pack=context_pack,
            normalization_report=normalization_report,
            deduplication_report=deduplication_report,
            fusion_report=fusion_report,
            path_validation_report=path_report,
        )
