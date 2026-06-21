from __future__ import annotations

from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import default_request
from lightrag_ext.us_dsl.query_semantic_profile import build_query_semantic_profile
from lightrag_ext.us_dsl.term_normalization_types import TermMappingRecord, TermScope
from lightrag_ext.us_dsl.term_registry import TermRegistry


def _registry() -> TermRegistry:
    registry = TermRegistry()
    registry.add(
        TermMappingRecord(
            term_mapping_id="m-confirmed",
            source_term="aliasone",
            canonical_term="CanonicalOne",
            source_language="en",
            canonical_language="en",
            synonym_type="BUSINESS_ALIAS",
            scope=TermScope(domain_code="domain-a", feature_key="feature-a", object_type="rule"),
            confidence=0.99,
            status="CONFIRMED",
            mapping_source="HUMAN_REVIEW",
        )
    )
    registry.add(
        TermMappingRecord(
            term_mapping_id="m-candidate",
            source_term="maybealias",
            canonical_term="CandidateCanonical",
            source_language="en",
            canonical_language="en",
            synonym_type="BUSINESS_ALIAS",
            scope=TermScope(domain_code="domain-a", feature_key="feature-a", object_type="rule"),
            confidence=0.75,
            status="CANDIDATE",
            mapping_source="MODEL_SUGGESTION",
        )
    )
    return registry


def test_query_profile_reuses_term_expander() -> None:
    profile = build_query_semantic_profile(
        default_request(query_text="aliasone current"),
        term_registry=_registry(),
    )
    assert "CanonicalOne" in profile.canonical_terms
    assert "TERM_EXPANDER_REUSED" in profile.reason_codes


def test_query_profile_reuses_version_intent() -> None:
    profile = build_query_semantic_profile(default_request(query_text="compare current and previous"))
    assert profile.version_intent == "COMPARE"
    assert "VERSION_INTENT_REUSED" in profile.reason_codes


def test_candidate_alias_is_not_strong_identity() -> None:
    profile = build_query_semantic_profile(
        default_request(query_text="maybealias"),
        term_registry=_registry(),
    )
    assert "maybealias" in profile.candidate_aliases
    assert "maybealias" not in profile.confirmed_aliases


def test_domain_feature_hints_are_not_hard_filters_by_default() -> None:
    profile = build_query_semantic_profile(default_request(domain_code="domain-a", feature_key="feature-a", strict_scope=False))
    assert profile.domain_hints == ["domain-a"]
    assert profile.feature_hints == ["feature-a"]
    assert "SCOPE_HINT_NOT_FILTER" in profile.reason_codes


def test_strict_scope_is_explicit() -> None:
    profile = build_query_semantic_profile(default_request(strict_scope=True))
    assert profile.strict_scope is True
    assert "STRICT_SCOPE_EXPLICIT" in profile.reason_codes
