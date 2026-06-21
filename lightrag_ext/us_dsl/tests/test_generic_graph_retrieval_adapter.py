from __future__ import annotations

from lightrag_ext.us_dsl.generic_graph_retrieval_adapter import GenericGraphRetrievalAdapter
from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request
from lightrag_ext.us_dsl.query_semantic_profile import build_query_semantic_profile


def test_generic_adapter_marks_low_trust() -> None:
    request = default_request()
    result = GenericGraphRetrievalAdapter(build_fixture_store().generic_candidates).search(request, build_query_semantic_profile(request))
    assert result
    assert all(item.trust_tier == "T4_BACKGROUND" and item.factual_weight <= 0.2 for item in result)


def test_generic_adapter_can_be_disabled() -> None:
    request = default_request()
    result = GenericGraphRetrievalAdapter(build_fixture_store().generic_candidates, enabled=False).search(
        request,
        build_query_semantic_profile(request),
    )
    assert result == []
