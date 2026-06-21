from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.hybrid_retrieval_generalization_guard import inspect_hybrid_retrieval_generalization
from lightrag_ext.us_dsl.hybrid_retrieval_service import HybridRetrievalService, InMemoryHybridRetrievalStore
from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request


def test_runtime_has_no_module_or_entity_name_hardcode() -> None:
    report = inspect_hybrid_retrieval_generalization(Path("lightrag_ext/us_dsl"))
    assert report.runtime_business_hardcode_count == 0
    assert report.entity_name_specific_weight_rule_count == 0


def test_unseen_module_fixture_uses_same_fusion_policy() -> None:
    store = build_fixture_store()
    for bucket in (store.raw_candidates, store.pfss_candidates, store.generic_candidates, store.issue_candidates):
        for candidate in bucket:
            candidate.domain_code = "unseen-domain"
            candidate.feature_key = "unseen-feature"
    result = HybridRetrievalService(
        InMemoryHybridRetrievalStore(
            raw_candidates=store.raw_candidates[:1],
            pfss_candidates=[item for item in store.pfss_candidates if item.candidate_id in {"pfss-entity-main", "pfss-relation-main", "pfss-path-main"}],
            generic_candidates=store.generic_candidates,
        )
    ).retrieve(default_request(domain_code="unseen-domain", feature_key="unseen-feature", top_k=6))
    assert result.fusion_report.fusion_method == "WEIGHTED_RRF"
    assert result.fallback.state == "HYBRID_EVIDENCE_READY"
