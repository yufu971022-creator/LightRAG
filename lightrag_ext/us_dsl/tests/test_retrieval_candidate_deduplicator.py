from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store
from lightrag_ext.us_dsl.retrieval_candidate_deduplicator import deduplicate_retrieval_candidates
from lightrag_ext.us_dsl.retrieval_candidate_normalizer import normalize_retrieval_candidates


def _deduped():
    store = build_fixture_store()
    normalized, _ = normalize_retrieval_candidates(store.raw_candidates + store.pfss_candidates + store.generic_candidates)
    return deduplicate_retrieval_candidates(normalized)


def test_semantic_identity_deduplicates_cross_channel_hits() -> None:
    result, report = _deduped()
    assert report.input_count > report.output_count
    assert len([item for item in result if item.stable_identity_key == "identity:rule-main"]) == 1


def test_raw_evidence_is_preserved_after_semantic_dedup() -> None:
    result, report = _deduped()
    winner = next(item for item in result if item.stable_identity_key == "identity:rule-main")
    assert report.raw_evidence_preserved is True
    assert any(evidence.text_hash == "hash-a" for evidence in winner.evidence)


def test_generic_duplicate_does_not_override_pfss() -> None:
    result, report = _deduped()
    winner = next(item for item in result if item.stable_identity_key == "identity:rule-main")
    assert winner.channel.startswith("PFSS")
    assert report.generic_overrode_pfss_count == 0


def test_path_signature_dedup_is_deterministic() -> None:
    first, report = _deduped()
    second, _ = _deduped()
    assert [item.candidate_id for item in first] == [item.candidate_id for item in second]
    assert report.deterministic_path_signature is True
