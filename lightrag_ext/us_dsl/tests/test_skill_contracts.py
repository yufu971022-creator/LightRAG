from __future__ import annotations

from lightrag_ext.us_dsl.skill_contracts import REQUIRED_SKILL_IDS, build_skill_contracts


def test_all_registered_skills_have_contracts() -> None:
    contracts = build_skill_contracts()
    assert set(REQUIRED_SKILL_IDS).issubset(contracts)


def test_skill_contract_has_preconditions_and_postconditions() -> None:
    for contract in build_skill_contracts().values():
        assert contract.preconditions
        assert contract.postconditions
        assert contract.output_schema
        assert contract.side_effect_policy == "NO_SIDE_EFFECTS_OR_STORAGE_WRITES"
