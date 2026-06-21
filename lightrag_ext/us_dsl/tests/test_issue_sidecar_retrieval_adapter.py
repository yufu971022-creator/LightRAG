from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request
from lightrag_ext.us_dsl.issue_sidecar_retrieval_adapter import IssueSidecarRetrievalAdapter
from lightrag_ext.us_dsl.query_semantic_profile import build_query_semantic_profile


def test_issue_adapter_returns_warnings_not_facts() -> None:
    request = default_request()
    result = IssueSidecarRetrievalAdapter(build_fixture_store().issue_candidates).search(request, build_query_semantic_profile(request))
    assert result
    assert all(item.factual_weight == 0.0 and item.trust_tier == "T5_WARNING" for item in result)


def test_version_context_is_attached() -> None:
    request = default_request(query_text="compare history")
    result = IssueSidecarRetrievalAdapter(build_fixture_store().issue_candidates).search(request, build_query_semantic_profile(request))
    assert any(item.channel == "VERSION_CONTEXT" and item.version_intent == "COMPARE" for item in result)
