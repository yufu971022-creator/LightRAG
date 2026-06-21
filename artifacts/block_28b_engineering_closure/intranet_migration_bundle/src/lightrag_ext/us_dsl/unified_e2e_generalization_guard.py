from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .unified_e2e_types import to_plain_dict

RUNTIME_FILES = [
    "unified_e2e_types.py",
    "unified_e2e_trace.py",
    "unified_e2e_state_machine.py",
    "unified_e2e_pipeline.py",
    "unified_e2e_orchestrator.py",
    "unified_e2e_consistency_validator.py",
    "unified_e2e_generalization_guard.py",
    "design_output_quality_harness.py",
    "design_quality_types.py",
    "evidence_citation_gate.py",
    "term_identity_gate.py",
    "version_safety_gate.py",
    "impact_breadth_gate.py",
    "fact_promotion_gate.py",
    "insufficient_evidence_gate.py",
]

_FORBIDDEN_TERM_HEX = (
    "e58fafe68ea5e58f97e8a18ce8a18c",
    "e8afa2e4bbb7",
    "e5a496e6b187",
    "e4bfa1e794a8e8af81",
    "42616e6b20537461747573",
    "537769667420436f6465",
    "43757272656e742048616e646c6572",
    "5472616e7366657220546f",
)


@dataclass(frozen=True)
class UnifiedE2EAntiHardcodeReport:
    runtime_module_branch_count: int = 0
    entity_name_specific_rule_count: int = 0
    module_specific_weight_count: int = 0
    module_specific_skill_count: int = 0
    fixture_runtime_coupling_count: int = 0
    file_name_controls_runtime_logic_count: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)
    scanned_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


def scan_unified_e2e_runtime(root: Path, files: list[str] | None = None) -> UnifiedE2EAntiHardcodeReport:
    base = root / "lightrag_ext" / "us_dsl"
    selected = files or RUNTIME_FILES
    counters = {
        "runtime_module_branch_count": 0,
        "entity_name_specific_rule_count": 0,
        "module_specific_weight_count": 0,
        "module_specific_skill_count": 0,
        "fixture_runtime_coupling_count": 0,
        "file_name_controls_runtime_logic_count": 0,
    }
    findings: list[dict[str, Any]] = []
    for relative in selected:
        path = base / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        _count(r"if\s+.*module_(?:code|name).*==", "runtime_module_branch_count", text, relative, counters, findings)
        _count(rf"(?:{_forbidden_pattern()}).*(?:route|score|gate|skill|weight|type|version)", "entity_name_specific_rule_count", text, relative, counters, findings)
        _count(r"if\s+.*module_(?:code|name).*weight", "module_specific_weight_count", text, relative, counters, findings)
        _count(r"(?:LC|FX|PAYMENT|BANK)_.*SKILL", "module_specific_skill_count", text, relative, counters, findings)
        _count(r"if\s+.*(?:file_?name|filename).*==", "file_name_controls_runtime_logic_count", text, relative, counters, findings)
    return UnifiedE2EAntiHardcodeReport(scanned_files=selected, findings=findings, **counters)


def _count(pattern: str, key: str, text: str, path: str, counters: dict[str, int], findings: list[dict[str, Any]]) -> None:
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
    counters[key] += len(matches)
    for match in matches:
        findings.append({"file": path, "line": text.count("\n", 0, match.start()) + 1, "kind": key})


def _forbidden_pattern() -> str:
    return "|".join(re.escape(bytes.fromhex(item).decode("utf-8")) for item in _FORBIDDEN_TERM_HEX)
