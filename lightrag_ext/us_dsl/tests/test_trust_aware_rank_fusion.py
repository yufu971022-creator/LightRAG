from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request
from lightrag_ext.us_dsl.query_semantic_profile import build_query_semantic_profile
from lightrag_ext.us_dsl.retrieval_candidate_deduplicator import deduplicate_retrieval_candidates
from lightrag_ext.us_dsl.retrieval_candidate_normalizer import normalize_retrieval_candidates
from lightrag_ext.us_dsl.trust_aware_rank_fusion import fuse_retrieval_candidates


def _fused():
    store = build_fixture_store()
    candidates = store.raw_candidates + store.pfss_candidates + store.generic_candidates + store.issue_candidates
    normalized, _ = normalize_retrieval_candidates(candidates)
    deduped, _ = deduplicate_retrieval_candidates(normalized)
    profile = build_query_semantic_profile(default_request(domain_code="domain-a", feature_key="feature-a"))
    return fuse_retrieval_candidates(deduped, profile)


def test_weighted_rrf_is_deterministic() -> None:
    first, first_report = _fused()
    second, _ = _fused()
    assert [item.candidate_id for item in first] == [item.candidate_id for item in second]
    assert first_report.fusion_method == "WEIGHTED_RRF"


def test_pfss_and_raw_rank_above_generic() -> None:
    fused, _ = _fused()
    generic_index = next(index for index, item in enumerate(fused) if item.channel == "GENERIC_GRAPH")
    pfss_index = next(index for index, item in enumerate(fused) if item.channel.startswith("PFSS"))
    assert pfss_index < generic_index


def test_issue_has_zero_factual_weight() -> None:
    _, report = _fused()
    assert report.issue_factual_weight == 0.0


def test_domain_match_boosts_without_default_filter() -> None:
    _, report = _fused()
    assert report.domain_match_boost_applied is True


def test_feature_match_boosts_without_default_filter() -> None:
    _, report = _fused()
    assert report.feature_match_boost_applied is True


def test_version_conflict_penalty_is_visible() -> None:
    _, report = _fused()
    assert report.version_conflict_penalty_visible is True


def test_missing_evidence_penalty_is_visible() -> None:
    _, report = _fused()
    assert report.missing_evidence_penalty_visible is True


def test_no_business_module_specific_weight() -> None:
    _, report = _fused()
    assert report.entity_name_specific_weight_rule_count == 0
