from __future__ import annotations

from lightrag_ext.us_dsl.generic_ner_type_policy import default_generic_ner_type_policy
from lightrag_ext.us_dsl.product_entity_type_registry import default_product_entity_type_registry


def test_generic_ner_types_are_not_pfss_types() -> None:
    registry = default_product_entity_type_registry()
    policy = default_generic_ner_type_policy()
    assert not (registry.all_types() & policy.generic_types)


def test_date_money_percent_are_treated_as_literals_or_attributes() -> None:
    policy = default_generic_ner_type_policy()
    assert policy.disposition("Date") == "IGNORE_AS_LITERAL"
    assert policy.disposition("Money") == "IGNORE_AS_LITERAL"
    assert policy.disposition("Percent") == "IGNORE_AS_LITERAL"
