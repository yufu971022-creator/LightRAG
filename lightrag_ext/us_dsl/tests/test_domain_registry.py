from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.domain_registry import (
    DOMAIN_OTHER,
    DomainRegistry,
    default_domain_registry,
)


def test_domain_registry_has_10_domains():
    registry = default_domain_registry()

    assert len(registry.all_domain_codes()) == 10
    assert "MasterData" in registry.all_domain_codes()
    assert "DataMigrationInitialization" in registry.all_domain_codes()


def test_unknown_domain_maps_to_other_or_warn():
    registry = DomainRegistry()

    assert registry.normalize_domain("unknown") == DOMAIN_OTHER
    assert registry.get("unknown").domain_code == DOMAIN_OTHER


def test_domain_registry_no_module_hardcode():
    source = Path("lightrag_ext/us_dsl/domain_registry.py").read_text()

    forbidden_terms = [
        "LCAB",
        "Acceptable Bank",
        "Bank Status",
        "Swift Code",
        "Transfer To",
        "Bank Default Confirmation",
        "eflowNum",
        "Suggested Rating",
        "FX",
    ]
    assert not [term for term in forbidden_terms if term in source]
