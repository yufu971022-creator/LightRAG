from __future__ import annotations

from lightrag_ext.us_dsl.skill_registry import build_skill_registry


def test_unimplemented_skill_is_not_marked_available() -> None:
    registry = build_skill_registry()
    assert registry.contracts["CODE_CONTEXT_HANDOFF"].capability_status == "PLANNED_NOT_IMPLEMENTED"


def test_existing_retrieval_adapter_is_registered() -> None:
    registry = build_skill_registry()
    assert registry.contracts["TRUSTED_KNOWLEDGE_RETRIEVAL"].capability_status == "ADAPTER_AVAILABLE"
    assert registry.contracts["TRUSTED_KNOWLEDGE_RETRIEVAL"].adapter_target


def test_existing_version_adapter_is_registered() -> None:
    registry = build_skill_registry()
    assert registry.contracts["VERSION_ANALYSIS"].capability_status == "ADAPTER_AVAILABLE"
    assert registry.contracts["VERSION_ANALYSIS"].adapter_target


def test_code_context_is_not_faked_when_unavailable() -> None:
    registry = build_skill_registry()
    contract = registry.contracts["CODE_CONTEXT_HANDOFF"]
    assert contract.capability_status == "PLANNED_NOT_IMPLEMENTED"
    assert contract.adapter_target == "future.code_context_adapter"


def test_skill_registry_has_no_module_specific_skill() -> None:
    assert build_skill_registry().module_specific_skill_count == 0
