from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_service import HybridRetrievalService
from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request


def test_hybrid_retrieval_service_produces_context_pack() -> None:
    result = HybridRetrievalService(build_fixture_store()).retrieve(default_request(top_k=12))
    assert result.profile.query_text
    assert result.fused_candidates
    assert result.context_pack.final_answer_generated is False
