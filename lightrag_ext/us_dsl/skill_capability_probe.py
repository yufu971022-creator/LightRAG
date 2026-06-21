from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from .harness_types import SkillContract, to_plain_dict
from .skill_contracts import ADAPTER_SKILL_IDS, PLANNED_SKILL_IDS, build_skill_contracts


@dataclass(frozen=True)
class SkillCapabilityEvidence:
    skill_id: str
    declared_status: str
    probed_status: str
    probed: bool
    evidence_source: str
    adapter_target: str | None
    adapter_importable: bool | None
    real_execution_performed: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


def probe_skill_capabilities(contracts: dict[str, SkillContract] | None = None) -> dict[str, SkillCapabilityEvidence]:
    contracts = contracts or build_skill_contracts()
    return {skill_id: _probe_contract(contract) for skill_id, contract in contracts.items()}


def _probe_contract(contract: SkillContract) -> SkillCapabilityEvidence:
    if contract.skill_id in ADAPTER_SKILL_IDS:
        importable = _adapter_importable(contract.adapter_target)
        status = contract.capability_status if importable else "BLOCKED_DEPENDENCY"
        return SkillCapabilityEvidence(
            skill_id=contract.skill_id,
            declared_status=contract.capability_status,
            probed_status=status,
            probed=True,
            evidence_source="importlib_spec_probe_without_execution",
            adapter_target=contract.adapter_target,
            adapter_importable=importable,
            real_execution_performed=False,
            notes=["adapter contract located" if importable else "adapter module not importable"],
        )
    if contract.skill_id in PLANNED_SKILL_IDS:
        return SkillCapabilityEvidence(
            skill_id=contract.skill_id,
            declared_status=contract.capability_status,
            probed_status="PLANNED_NOT_IMPLEMENTED",
            probed=True,
            evidence_source="explicit_unimplemented_capability_contract",
            adapter_target=contract.adapter_target,
            adapter_importable=False,
            real_execution_performed=False,
            notes=["not faked as available"],
        )
    return SkillCapabilityEvidence(
        skill_id=contract.skill_id,
        declared_status=contract.capability_status,
        probed_status=contract.capability_status,
        probed=True,
        evidence_source="local_deterministic_contract",
        adapter_target=contract.adapter_target,
        adapter_importable=None,
        real_execution_performed=False,
        notes=["no external execution required"],
    )


def _adapter_importable(adapter_target: str | None) -> bool:
    if not adapter_target or adapter_target.startswith("future."):
        return False
    module_name = adapter_target.split(":", 1)[0]
    return importlib.util.find_spec(module_name) is not None
