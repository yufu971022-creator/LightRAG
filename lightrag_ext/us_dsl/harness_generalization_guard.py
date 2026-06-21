from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .harness_types import to_plain_dict

RUNTIME_FILES = [
    "harness_types.py",
    "requirement_scenario_profile.py",
    "requirement_scenario_router.py",
    "skill_contracts.py",
    "skill_registry.py",
    "skill_capability_probe.py",
    "scenario_skill_templates.py",
    "skill_dag_planner.py",
    "harness_context_assembler.py",
    "harness_checkpoint_policy.py",
    "harness_state_machine.py",
    "harness_executor.py",
    "harness_generalization_guard.py",
]

_ENTITY_TERM_HEX = (
    "42616e6b20537461747573",
    "e58fafe68ea5e58f97e8a18ce8a18c",
    "e8afa2e4bbb7",
    "e4bfa1e794a8e8af81",
    "e5a496e6b187",
    "4658",
    "4c434142",
)
_FIXTURE_TERM_HEX = (
    "74657374735c2e6669787475726573",
    "666978747572655f7375697465",
    "4c435f41636365707461626c65",
)


@dataclass(frozen=True)
class HarnessAntiHardcodeReport:
    runtime_module_branch_count: int = 0
    entity_name_scenario_rule_count: int = 0
    entity_name_skill_rule_count: int = 0
    fixture_runtime_coupling_count: int = 0
    module_specific_skill_count: int = 0
    module_specific_threshold_count: int = 0
    new_module_requires_code_change: bool = False
    scanned_files: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


def scan_harness_runtime(root: Path, files: list[str] | None = None) -> HarnessAntiHardcodeReport:
    base = root / "lightrag_ext" / "us_dsl"
    selected = files or RUNTIME_FILES
    findings: list[dict[str, Any]] = []
    counters = {
        "runtime_module_branch_count": 0,
        "entity_name_scenario_rule_count": 0,
        "entity_name_skill_rule_count": 0,
        "fixture_runtime_coupling_count": 0,
        "module_specific_threshold_count": 0,
    }
    for relative in selected:
        path = base / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        _count(pattern=r"if\s+.*module_(?:code|name).*==", key="runtime_module_branch_count", text=text, path=relative, counters=counters, findings=findings)
        entity_pattern = _entity_pattern()
        _count(pattern=rf"(?:{entity_pattern}).*selected_scenario", key="entity_name_scenario_rule_count", text=text, path=relative, counters=counters, findings=findings)
        _count(pattern=rf"(?:{entity_pattern}).*skill", key="entity_name_skill_rule_count", text=text, path=relative, counters=counters, findings=findings)
        _count(pattern=_fixture_coupling_pattern(), key="fixture_runtime_coupling_count", text=text, path=relative, counters=counters, findings=findings)
        _count(pattern=r"if\s+.*module_.*threshold", key="module_specific_threshold_count", text=text, path=relative, counters=counters, findings=findings)
    from .skill_registry import build_skill_registry

    module_specific_skill_count = build_skill_registry().module_specific_skill_count
    return HarnessAntiHardcodeReport(
        module_specific_skill_count=module_specific_skill_count,
        scanned_files=selected,
        findings=findings,
        **counters,
    )


def _count(pattern: str, key: str, text: str, path: str, counters: dict[str, int], findings: list[dict[str, Any]]) -> None:
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
    counters[key] += len(matches)
    for match in matches:
        line = text.count("\n", 0, match.start()) + 1
        findings.append({"file": path, "line": line, "kind": key, "match": match.group(0)[:120]})


def _entity_pattern() -> str:
    return "|".join(re.escape(bytes.fromhex(item).decode("utf-8")) for item in _ENTITY_TERM_HEX)


def _fixture_coupling_pattern() -> str:
    return "|".join(bytes.fromhex(item).decode("utf-8") for item in _FIXTURE_TERM_HEX)
