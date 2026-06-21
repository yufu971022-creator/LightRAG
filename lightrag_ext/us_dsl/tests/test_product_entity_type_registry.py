from __future__ import annotations

import json

from lightrag_ext.us_dsl.product_entity_type_registry import PFSS_ENTITY_TYPES, default_product_entity_type_registry


def test_registry_contains_all_pfss_entity_types() -> None:
    registry = default_product_entity_type_registry()
    assert PFSS_ENTITY_TYPES <= registry.all_types()


def test_registry_is_domain_aware() -> None:
    registry = default_product_entity_type_registry()
    report_spec = registry.get("ReportSpec")
    assert "query_section" in report_spec.preferred_section_types
    assert registry.is_domain_allowed("ReportSpec", "MonitoringReport")


def test_registry_has_no_business_module_hardcode() -> None:
    registry_json = json.dumps(default_product_entity_type_registry().to_report(), ensure_ascii=False)
    assert "询价" not in registry_json
    assert "Inquiry" not in registry_json
