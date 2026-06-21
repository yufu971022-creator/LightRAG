from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_service import HybridRetrievalService, InMemoryHybridRetrievalStore
from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request


def _store_without_warnings() -> InMemoryHybridRetrievalStore:
    store = build_fixture_store()
    return InMemoryHybridRetrievalStore(
        raw_candidates=store.raw_candidates[:1],
        pfss_candidates=[item for item in store.pfss_candidates if item.candidate_id in {"pfss-entity-main", "pfss-relation-main", "pfss-path-main"}],
        generic_candidates=store.generic_candidates,
    )


def test_pfss_and_raw_produce_hybrid_ready() -> None:
    result = HybridRetrievalService(_store_without_warnings()).retrieve(default_request(top_k=6))
    assert result.fallback.state == "HYBRID_EVIDENCE_READY"


def test_raw_only_produces_text_fallback() -> None:
    store = build_fixture_store()
    result = HybridRetrievalService(InMemoryHybridRetrievalStore(raw_candidates=store.raw_candidates[:1])).retrieve(default_request())
    assert result.fallback.state == "TEXT_ONLY_FALLBACK"


def test_version_conflict_produces_warning_state() -> None:
    store = build_fixture_store()
    result = HybridRetrievalService(
        InMemoryHybridRetrievalStore(
            raw_candidates=store.raw_candidates[:1],
            pfss_candidates=[item for item in store.pfss_candidates if item.candidate_id == "pfss-path-version-warning"],
        )
    ).retrieve(default_request(top_k=3))
    assert result.fallback.state == "PFSS_WITH_VERSION_WARNING"


def test_generic_only_is_not_deterministic() -> None:
    store = build_fixture_store()
    result = HybridRetrievalService(InMemoryHybridRetrievalStore(generic_candidates=store.generic_candidates)).retrieve(default_request())
    assert result.fallback.state == "GENERIC_ONLY_LOW_TRUST"
    assert result.fallback.safe_for_deterministic_answer is False


def test_issue_only_state() -> None:
    store = build_fixture_store()
    result = HybridRetrievalService(InMemoryHybridRetrievalStore(issue_candidates=store.issue_candidates)).retrieve(default_request())
    assert result.fallback.state == "ISSUE_ONLY"


def test_empty_result_is_insufficient_evidence() -> None:
    result = HybridRetrievalService(InMemoryHybridRetrievalStore()).retrieve(default_request())
    assert result.fallback.state == "INSUFFICIENT_EVIDENCE"


def test_strict_scope_empty_is_reported() -> None:
    result = HybridRetrievalService(_store_without_warnings()).retrieve(
        default_request(domain_code="other-domain", strict_scope=True)
    )
    assert result.fallback.state == "STRICT_SCOPE_EMPTY"
