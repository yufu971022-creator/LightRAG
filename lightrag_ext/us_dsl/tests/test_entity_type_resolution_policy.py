from __future__ import annotations

from lightrag_ext.us_dsl.entity_type_resolution_policy import EntityTypeResolutionPolicy
from lightrag_ext.us_dsl.entity_type_resolution_types import EntityTypeCandidate


def test_generic_ner_type_cannot_enter_pfss() -> None:
    decision = EntityTypeResolutionPolicy().decide(
        original_entity_type="Location",
        candidates=[EntityTypeCandidate("Location", 0.99, "GENERIC_NER", ["generic"], {})],
        evidence_complete=True,
    )
    assert decision.decision == "BLOCKED_GENERIC_TYPE"
    assert decision.blocked_from_pfss is True


def test_review_required_type_cannot_enter_pfss() -> None:
    decision = EntityTypeResolutionPolicy().decide(
        original_entity_type="Misc",
        candidates=[EntityTypeCandidate("FieldSpec", 0.80, "SECTION_DOMAIN_HEURISTIC", ["lexical"], {})],
        evidence_complete=True,
    )
    assert decision.decision == "CANDIDATE_REVIEW"
    assert decision.blocked_from_pfss is True


def test_resolved_safe_type_can_enter_pfss() -> None:
    decision = EntityTypeResolutionPolicy().decide(
        original_entity_type="Misc",
        candidates=[EntityTypeCandidate("FieldSpec", 0.95, "STRUCTURAL_PARSER", ["field_table"], {})],
        evidence_complete=True,
    )
    assert decision.resolved_entity_type == "FieldSpec"
    assert decision.blocked_from_pfss is False
