from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store
from lightrag_ext.us_dsl.retrieval_candidate_normalizer import normalize_retrieval_candidates


def test_channel_scores_are_normalized_before_fusion() -> None:
    store = build_fixture_store()
    normalized, report = normalize_retrieval_candidates(store.raw_candidates + store.pfss_candidates + store.generic_candidates)
    assert normalized
    assert all(0.0 <= item.normalized_score <= 1.0 for item in normalized)
    assert "RAW_TEXT" in report.channel_counts


def test_raw_cosine_is_not_directly_added_to_graph_score() -> None:
    store = build_fixture_store()
    _, report = normalize_retrieval_candidates(store.raw_candidates + store.pfss_candidates)
    assert report.direct_raw_score_addition_used is False
