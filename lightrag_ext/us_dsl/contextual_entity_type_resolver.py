from __future__ import annotations

from .entity_type_resolution_policy import EntityTypeResolutionPolicy
from .entity_type_resolution_types import EntityTypeCandidate, EntityTypeResolutionContext, EntityTypeResolutionDecision
from .generic_ner_type_policy import GenericNERTypePolicy, default_generic_ner_type_policy
from .product_entity_type_registry import ProductEntityTypeRegistry, default_product_entity_type_registry
from .relation_type_signature_registry import RelationTypeSignatureRegistry, default_relation_type_signature_registry


class ContextualEntityTypeResolver:
    def __init__(
        self,
        *,
        registry: ProductEntityTypeRegistry | None = None,
        generic_policy: GenericNERTypePolicy | None = None,
        signature_registry: RelationTypeSignatureRegistry | None = None,
        policy: EntityTypeResolutionPolicy | None = None,
    ) -> None:
        self.registry = registry or default_product_entity_type_registry()
        self.generic_policy = generic_policy or default_generic_ner_type_policy()
        self.signature_registry = signature_registry or default_relation_type_signature_registry()
        self.policy = policy or EntityTypeResolutionPolicy(registry=self.registry, generic_policy=self.generic_policy)

    def resolve(self, context: EntityTypeResolutionContext) -> EntityTypeResolutionDecision:
        candidates = self.candidates(context)
        return self.policy.decide(
            original_entity_type=context.original_entity_type,
            candidates=candidates,
            evidence_complete=bool(context.evidence_text and context.text_unit_id),
        )

    def candidates(self, context: EntityTypeResolutionContext) -> list[EntityTypeCandidate]:
        candidates: list[EntityTypeCandidate] = []
        if context.explicit_dsl_type:
            if self.registry.contains(context.explicit_dsl_type):
                candidates.append(EntityTypeCandidate(context.explicit_dsl_type, 1.0, "EXPLICIT_DSL", ["explicit_valid_dsl_type"], _evidence(context)))
            else:
                candidates.append(EntityTypeCandidate(context.explicit_dsl_type, 0.2, "EXPLICIT_DSL", ["explicit_type_not_in_registry"], _evidence(context)))
        for type_code in _split_types(context.confirmed_config_type):
            candidates.append(EntityTypeCandidate(type_code, 0.98, "CONFIRMED_CONFIG", ["confirmed_config_type"], _evidence(context)))
        for type_code in _split_types(context.structural_type):
            candidates.append(EntityTypeCandidate(type_code, 0.95, "STRUCTURAL_PARSER", ["structural_parser_type"], _evidence(context)))
        structural = _structural_candidate(context)
        if structural:
            candidates.append(structural)
        relation_type = context.relation_signature_type or self.signature_registry.type_for_role(context.relation_type, context.relation_role)
        if relation_type:
            candidates.append(EntityTypeCandidate(relation_type, 0.93, "RELATION_SIGNATURE", ["relation_signature_unique_type"], _evidence(context)))
        heuristic = _section_domain_candidate(context)
        if heuristic:
            candidates.append(heuristic)
        lexical = _lexical_candidate(context, self.registry)
        if lexical:
            candidates.append(lexical)
        if context.original_entity_type:
            if self.generic_policy.is_generic_ner_type(context.original_entity_type):
                candidates.append(EntityTypeCandidate(context.original_entity_type, 0.40, "GENERIC_NER", ["generic_ner_weak_hint"], _evidence(context)))
            elif self.registry.contains(context.original_entity_type):
                candidates.append(EntityTypeCandidate(context.original_entity_type, 0.88, "MODEL_CANDIDATE", ["model_candidate_pfss_type"], _evidence(context)))
        return candidates


def resolve_entity_type(context: EntityTypeResolutionContext) -> EntityTypeResolutionDecision:
    return ContextualEntityTypeResolver().resolve(context)


def _structural_candidate(context: EntityTypeResolutionContext) -> EntityTypeCandidate | None:
    section = context.section_type or ""
    table = (context.table_context or "").casefold()
    field = (context.field_context or "").casefold()
    heading = context.heading_context or ""
    if section in {"query_section", "list_definition", "result_grid", "export_section", "report_rule"}:
        if context.relation_role in {"target", "object", "tgt"} or field or _looks_like_field_or_column(context.original_entity_name):
            return EntityTypeCandidate("FieldSpec", 0.95, "STRUCTURAL_PARSER", ["field_or_column_structure"], _evidence(context))
        return EntityTypeCandidate("ReportSpec", 0.95, "STRUCTURAL_PARSER", ["query_list_report_structure"], _evidence(context))
    if section in {"field_table", "query_condition"} or table in {"field", "column"}:
        return EntityTypeCandidate("FieldSpec", 0.95, "STRUCTURAL_PARSER", ["field_table_structure"], _evidence(context))
    if section == "task_rule":
        return EntityTypeCandidate("TaskRule", 0.95, "STRUCTURAL_PARSER", ["task_section_structure"], _evidence(context))
    if section in {"api_desc", "integration_section"}:
        return EntityTypeCandidate("IntegrationEndpoint", 0.95, "STRUCTURAL_PARSER", ["api_section_structure"], _evidence(context))
    if section in {"migration_rule", "migration_section"}:
        return EntityTypeCandidate("DataMigrationSpec", 0.95, "STRUCTURAL_PARSER", ["migration_section_structure"], _evidence(context))
    if section in {"access_audit", "business_rule", "audit_rule"}:
        return EntityTypeCandidate("RuleAtom", 0.95, "STRUCTURAL_PARSER", ["rule_section_structure"], _evidence(context))
    if section in {"master_data", "domain_object"}:
        return EntityTypeCandidate("DomainObject", 0.95, "STRUCTURAL_PARSER", ["domain_object_structure"], _evidence(context))
    if section in {"page_title", "menu_entry", "feature_entry"} or "页面" in heading:
        return EntityTypeCandidate("FeatureCatalog", 0.95, "STRUCTURAL_PARSER", ["feature_page_structure"], _evidence(context))
    return None


def _section_domain_candidate(context: EntityTypeResolutionContext) -> EntityTypeCandidate | None:
    if context.primary_domain == "MonitoringReport" and context.section_type in {"query_section", "report_rule", "list_definition"}:
        return EntityTypeCandidate("ReportSpec", 0.90, "SECTION_DOMAIN_HEURISTIC", ["monitoring_report_query_context"], _evidence(context))
    return None


def _lexical_candidate(context: EntityTypeResolutionContext, registry: ProductEntityTypeRegistry) -> EntityTypeCandidate | None:
    text = " ".join([context.original_entity_name, context.canonical_term or "", context.evidence_text or ""]).casefold()
    matches: list[EntityTypeCandidate] = []
    for type_code in sorted(registry.all_types()):
        definition = registry.get(type_code)
        if any(cue.casefold() in text for cue in definition.lexical_cues):
            matches.append(EntityTypeCandidate(type_code, 0.80, "SECTION_DOMAIN_HEURISTIC", ["lexical_cue_only"], _evidence(context)))
    if len(matches) == 1:
        return matches[0]
    if matches:
        # Keep lexical-only ambiguous signals below auto threshold; policy will require review or use stronger candidates.
        return sorted(matches, key=lambda item: item.candidate_type)[0]
    return None


def _evidence(context: EntityTypeResolutionContext) -> dict[str, object]:
    return {
        "text_unit_id": context.text_unit_id,
        "source_span": context.source_span,
        "evidence_text": context.evidence_text,
        "section_type": context.section_type,
        "original_entity_name": context.original_entity_name,
        "original_entity_type": context.original_entity_type,
    }


def _split_types(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split("|") if item.strip()]


def _looks_like_field_or_column(name: str) -> bool:
    return any(marker in name for marker in ["字段", "列名", "表头"]) or name.endswith("列")
