from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request
from lightrag_ext.us_dsl.query_semantic_profile import build_query_semantic_profile
from lightrag_ext.us_dsl.raw_text_retrieval_adapter import RawTextRetrievalAdapter


def test_raw_adapter_returns_direct_evidence() -> None:
    request = default_request()
    result = RawTextRetrievalAdapter(build_fixture_store().raw_candidates).search(request, build_query_semantic_profile(request))
    assert result
    assert all(item.channel == "RAW_TEXT" for item in result)
    assert all(item.evidence for item in result)


def test_raw_adapter_excludes_deleted_active_projection() -> None:
    request = default_request(include_historical=False)
    result = RawTextRetrievalAdapter(build_fixture_store().raw_candidates).search(request, build_query_semantic_profile(request))
    ids = {item.candidate_id for item in result}
    assert "raw-deleted" not in ids
    assert "raw-historical" not in ids
