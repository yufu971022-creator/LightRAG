from __future__ import annotations

import json

from lightrag_ext.us_dsl.hybrid_retrieval_service import HybridRetrievalService, InMemoryHybridRetrievalStore
from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request
from lightrag_ext.us_dsl.hybrid_retrieval_types import to_plain_dict


def _context_with_warnings():
    return HybridRetrievalService(build_fixture_store()).retrieve(default_request(top_k=12)).context_pack


def test_context_pack_contains_direct_evidence() -> None:
    pack = _context_with_warnings()
    assert pack.direct_evidence
    assert pack.citations


def test_context_pack_contains_score_explanations() -> None:
    pack = _context_with_warnings()
    assert pack.score_explanations
    assert all("fused_score" in item for item in pack.score_explanations)


def test_context_pack_keeps_version_warning() -> None:
    pack = _context_with_warnings()
    assert any(item.channel == "VERSION_CONTEXT" for item in pack.issue_warnings)


def test_context_pack_separates_factual_tentative_generic() -> None:
    pack = _context_with_warnings()
    assert pack.factual_candidates
    assert pack.tentative_paths
    assert pack.generic_context


def test_context_pack_does_not_promote_issue_to_fact() -> None:
    pack = _context_with_warnings()
    fact_ids = {item.candidate_id for item in pack.factual_candidates}
    assert "issue-version-conflict" not in fact_ids


def test_context_token_budget_keeps_at_least_one_evidence_per_fact() -> None:
    store = build_fixture_store()
    pack = HybridRetrievalService(
        InMemoryHybridRetrievalStore(raw_candidates=store.raw_candidates[:1], pfss_candidates=store.pfss_candidates[:3])
    ).retrieve(default_request(top_k=5)).context_pack
    assert pack.token_budget is not None
    assert pack.token_budget.token_budget_preserved_required_evidence is True


def test_context_pack_is_serializable() -> None:
    pack = _context_with_warnings()
    json.dumps(to_plain_dict(pack), ensure_ascii=False)
