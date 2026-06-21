from __future__ import annotations

from dataclasses import dataclass

from .harness_types import SkillContract, to_plain_dict
from .skill_contracts import ALL_SKILL_IDS, build_skill_contracts


@dataclass(frozen=True)
class SkillRegistrySnapshot:
    contracts: dict[str, SkillContract]
    registered_skill_count: int
    available_skill_count: int
    adapter_available_skill_count: int
    planned_not_implemented_skill_count: int
    blocked_dependency_skill_count: int
    disabled_skill_count: int
    module_specific_skill_count: int

    def to_dict(self) -> dict[str, object]:
        data = to_plain_dict(self)
        data["contracts"] = {skill_id: to_plain_dict(contract) for skill_id, contract in self.contracts.items()}
        return data


def build_skill_registry() -> SkillRegistrySnapshot:
    contracts = build_skill_contracts()
    missing = sorted(set(ALL_SKILL_IDS) - set(contracts))
    if missing:
        raise ValueError(f"missing skill contracts: {missing}")
    return SkillRegistrySnapshot(
        contracts=contracts,
        registered_skill_count=len(contracts),
        available_skill_count=sum(1 for item in contracts.values() if item.capability_status == "AVAILABLE"),
        adapter_available_skill_count=sum(1 for item in contracts.values() if item.capability_status == "ADAPTER_AVAILABLE"),
        planned_not_implemented_skill_count=sum(1 for item in contracts.values() if item.capability_status == "PLANNED_NOT_IMPLEMENTED"),
        blocked_dependency_skill_count=sum(1 for item in contracts.values() if item.capability_status == "BLOCKED_DEPENDENCY"),
        disabled_skill_count=sum(1 for item in contracts.values() if item.capability_status == "DISABLED"),
        module_specific_skill_count=count_module_specific_skills(contracts),
    )


def count_module_specific_skills(contracts: dict[str, SkillContract]) -> int:
    # Runtime skill ids must describe generic capabilities, not business modules or entity names.
    forbidden_fragments = {"FX", "LC", "BANK", "QUOTE", "ACCOUNT", "PAYMENT", "CASH", "RISK"}
    return sum(1 for skill_id in contracts if set(skill_id.split("_")) & forbidden_fragments)
