from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request
from lightrag_ext.us_dsl.pfss_retrieval_adapter import PfssRetrievalAdapter
from lightrag_ext.us_dsl.query_semantic_profile import build_query_semantic_profile


def test_pfss_adapter_returns_entity_relation_and_path() -> None:
    request = default_request(top_k=10)
    result = PfssRetrievalAdapter(build_fixture_store().pfss_candidates).search(request, build_query_semantic_profile(request))
    kinds = {item.kind for item in result}
    assert {"ENTITY", "RELATION", "PATH"}.issubset(kinds)


def test_pfss_adapter_reads_sidecar_evidence() -> None:
    request = default_request(top_k=10)
    result = PfssRetrievalAdapter(build_fixture_store().pfss_candidates).search(request, build_query_semantic_profile(request))
    assert any(item.candidate_id == "pfss-path-main" and len(item.evidence) >= 2 for item in result)
