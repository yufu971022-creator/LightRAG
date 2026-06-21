from __future__ import annotations

from dataclasses import dataclass

from .entity_type_resolution_types import EntityTypeCandidate, EntityTypeResolutionDecision
from .generic_ner_type_policy import GenericNERTypePolicy, default_generic_ner_type_policy
from .product_entity_type_registry import ProductEntityTypeRegistry, default_product_entity_type_registry

SOURCE_DECISION = {
    "EXPLICIT_DSL": "EXPLICIT_ACCEPTED",
    "CONFIRMED_CONFIG": "CONFIG_RESOLVED",
    "STRUCTURAL_PARSER": "STRUCTURE_RESOLVED",
    "RELATION_SIGNATURE": "RELATION_RESOLVED",
    "SECTION_DOMAIN_HEURISTIC": "HEURISTIC_RESOLVED",
}
SOURCE_PRIORITY = {
    "EXPLICIT_DSL": 1,
    "CONFIRMED_CONFIG": 2,
    "STRUCTURAL_PARSER": 3,
    "RELATION_SIGNATURE": 4,
    "SECTION_DOMAIN_HEURISTIC": 5,
    "GENERIC_NER": 6,
    "MODEL_CANDIDATE": 7,
}


@dataclass(frozen=True)
class EntityTypeResolutionPolicyConfig:
    auto_accept_threshold: float = 0.90
    review_threshold: float = 0.65


class EntityTypeResolutionPolicy:
    def __init__(
        self,
        *,
        config: EntityTypeResolutionPolicyConfig | None = None,
        registry: ProductEntityTypeRegistry | None = None,
        generic_policy: GenericNERTypePolicy | None = None,
    ) -> None:
        self.config = config or EntityTypeResolutionPolicyConfig()
        self.registry = registry or default_product_entity_type_registry()
        self.generic_policy = generic_policy or default_generic_ner_type_policy()

    def decide(
        self,
        *,
        original_entity_type: str | None,
        candidates: list[EntityTypeCandidate],
        evidence_complete: bool,
        old_semantic_object_id: str | None = None,
        new_semantic_object_id: str | None = None,
    ) -> EntityTypeResolutionDecision:
        sorted_candidates = sorted(candidates, key=lambda item: (SOURCE_PRIORITY.get(item.source, 99), -item.score, item.candidate_type))
        if not sorted_candidates:
            return EntityTypeResolutionDecision(
                original_entity_type=original_entity_type,
                resolved_entity_type=None,
                decision="NO_SAFE_TYPE",
                confidence=0.0,
                candidate_types=[],
                selected_type=None,
                requires_review=True,
                blocked_from_pfss=True,
                reason_codes=["no_candidate_type"],
                signals_used=[],
                signals_rejected=["no_candidate_type"],
                identity_rekey_required=bool(old_semantic_object_id and new_semantic_object_id and old_semantic_object_id != new_semantic_object_id),
                old_semantic_object_id=old_semantic_object_id,
                new_semantic_object_id=new_semantic_object_id,
            )
        top_priority = SOURCE_PRIORITY.get(sorted_candidates[0].source, 99)
        top = [item for item in sorted_candidates if SOURCE_PRIORITY.get(item.source, 99) == top_priority and item.score == sorted_candidates[0].score]
        top_types = {item.candidate_type for item in top}
        if len(top_types) > 1:
            return EntityTypeResolutionDecision(
                original_entity_type=original_entity_type,
                resolved_entity_type=None,
                decision="CONFLICT",
                confidence=sorted_candidates[0].score,
                candidate_types=sorted_candidates,
                selected_type=None,
                conflict_types=sorted(top_types),
                requires_review=True,
                blocked_from_pfss=True,
                reason_codes=["highest_priority_type_conflict"],
                signals_used=_signals_used(sorted_candidates[0]),
                signals_rejected=_signals_rejected(sorted_candidates, sorted_candidates[0], extra=["conflicting_top_priority_candidates"]),
                identity_rekey_required=bool(old_semantic_object_id and new_semantic_object_id and old_semantic_object_id != new_semantic_object_id),
                old_semantic_object_id=old_semantic_object_id,
                new_semantic_object_id=new_semantic_object_id,
            )
        best = sorted_candidates[0]
        if self.generic_policy.is_generic_ner_type(best.candidate_type):
            return EntityTypeResolutionDecision(
                original_entity_type=original_entity_type,
                resolved_entity_type=None,
                decision="BLOCKED_GENERIC_TYPE",
                confidence=best.score,
                candidate_types=sorted_candidates,
                selected_type=None,
                requires_review=True,
                blocked_from_pfss=True,
                reason_codes=["generic_ner_type_blocked"],
                signals_used=_signals_used(best),
                signals_rejected=_signals_rejected(sorted_candidates, best, extra=["generic_ner_only_not_pfss_safe"]),
                identity_rekey_required=bool(old_semantic_object_id and new_semantic_object_id and old_semantic_object_id != new_semantic_object_id),
                old_semantic_object_id=old_semantic_object_id,
                new_semantic_object_id=new_semantic_object_id,
            )
        if not self.registry.contains(best.candidate_type):
            return EntityTypeResolutionDecision(
                original_entity_type=original_entity_type,
                resolved_entity_type=None,
                decision="NO_SAFE_TYPE",
                confidence=best.score,
                candidate_types=sorted_candidates,
                selected_type=None,
                requires_review=True,
                blocked_from_pfss=True,
                reason_codes=["candidate_not_in_pfss_registry"],
                signals_used=_signals_used(best),
                signals_rejected=_signals_rejected(sorted_candidates, best, extra=["candidate_not_in_pfss_registry"]),
            )
        if best.score >= self.config.auto_accept_threshold and evidence_complete:
            return EntityTypeResolutionDecision(
                original_entity_type=original_entity_type,
                resolved_entity_type=best.candidate_type,
                decision=SOURCE_DECISION.get(best.source, "HEURISTIC_RESOLVED"),  # type: ignore[arg-type]
                confidence=best.score,
                candidate_types=sorted_candidates,
                selected_type=best.candidate_type,
                blocked_from_pfss=False,
                reason_codes=[*best.reason_codes, "auto_accept_threshold_met"],
                signals_used=_signals_used(best),
                signals_rejected=_signals_rejected(sorted_candidates, best),
                identity_rekey_required=bool(old_semantic_object_id and new_semantic_object_id and old_semantic_object_id != new_semantic_object_id),
                old_semantic_object_id=old_semantic_object_id,
                new_semantic_object_id=new_semantic_object_id,
            )
        if best.score >= self.config.review_threshold:
            return EntityTypeResolutionDecision(
                original_entity_type=original_entity_type,
                resolved_entity_type=best.candidate_type,
                decision="CANDIDATE_REVIEW",
                confidence=best.score,
                candidate_types=sorted_candidates,
                selected_type=best.candidate_type,
                requires_review=True,
                blocked_from_pfss=True,
                reason_codes=[*best.reason_codes, "below_auto_accept_threshold" if evidence_complete else "missing_required_evidence"],
                signals_used=_signals_used(best),
                signals_rejected=_signals_rejected(sorted_candidates, best, extra=["below_auto_accept_threshold" if evidence_complete else "missing_required_evidence"]),
            )
        return EntityTypeResolutionDecision(
            original_entity_type=original_entity_type,
            resolved_entity_type=None,
            decision="NO_SAFE_TYPE",
            confidence=best.score,
            candidate_types=sorted_candidates,
            selected_type=None,
            requires_review=True,
            blocked_from_pfss=True,
            reason_codes=[*best.reason_codes, "below_review_threshold"],
            signals_used=_signals_used(best),
            signals_rejected=_signals_rejected(sorted_candidates, best, extra=["below_review_threshold"]),
        )


def _signals_used(candidate: EntityTypeCandidate) -> list[str]:
    by_source = {
        "EXPLICIT_DSL": ["explicit_dsl_type"],
        "CONFIRMED_CONFIG": ["confirmed_type_configuration"],
        "STRUCTURAL_PARSER": ["document_structure", "section_type", "structural_context"],
        "RELATION_SIGNATURE": ["relation_signature", "relation_role"],
        "SECTION_DOMAIN_HEURISTIC": ["primary_domain", "feature_context", "generic_lexical_cue"],
        "GENERIC_NER": ["generic_ner_candidate"],
        "MODEL_CANDIDATE": ["model_candidate_type"],
    }
    return sorted({*by_source.get(candidate.source, []), *candidate.reason_codes})


def _signals_rejected(candidates: list[EntityTypeCandidate], selected: EntityTypeCandidate, *, extra: list[str] | None = None) -> list[str]:
    rejected = {f"candidate:{item.source}:{item.candidate_type}" for item in candidates if item is not selected}
    if extra:
        rejected.update(extra)
    return sorted(rejected)
