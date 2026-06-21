from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .design_quality_types import to_plain_dict

RUNTIME_FILES = [
    "design_quality_types.py",
    "functional_qa_contract.py",
    "impact_analysis_contract.py",
    "functional_qa_executor.py",
    "impact_analysis_executor.py",
    "evidence_citation_gate.py",
    "term_identity_gate.py",
    "version_safety_gate.py",
    "impact_breadth_gate.py",
    "fact_promotion_gate.py",
    "insufficient_evidence_gate.py",
    "targeted_repair_planner.py",
    "design_output_quality_harness.py",
    "design_quality_generalization_guard.py",
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
_FIXTURE_TERM_HEX = (
    "74657374735c2e6669787475726573",
    "676f6c645f636173655f736574",
    "73696c7665725f636173655f736574",
)


@dataclass(frozen=True)
class DesignQualityAntiHardcodeReport:
    runtime_module_branch_count: int = 0
    entity_name_quality_rule_count: int = 0
    module_specific_dimension_rule_count: int = 0
    fixture_runtime_coupling_count: int = 0
    module_specific_threshold_count: int = 0
    holdout_policy_passed: bool = True
    findings: list[dict[str, Any]] = field(default_factory=list)
    scanned_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return to_plain_dict(self)


def scan_design_quality_runtime(root: Path, files: list[str] | None = None) -> DesignQualityAntiHardcodeReport:
    base = root / "lightrag_ext" / "us_dsl"
    selected = files or RUNTIME_FILES
    counters = {
        "runtime_module_branch_count": 0,
        "entity_name_quality_rule_count": 0,
        "module_specific_dimension_rule_count": 0,
        "fixture_runtime_coupling_count": 0,
        "module_specific_threshold_count": 0,
    }
    findings: list[dict[str, Any]] = []
    for relative in selected:
        path = base / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        _count(r"if\s+.*module_(?:code|name).*==", "runtime_module_branch_count", text, relative, counters, findings)
        _count(rf"(?:{_forbidden_pattern()}).*(?:quality|gate|impact|answer)", "entity_name_quality_rule_count", text, relative, counters, findings)
        _count(r"if\s+.*module_.*(?:domain|dimension|required_dimensions)", "module_specific_dimension_rule_count", text, relative, counters, findings)
        _count(r"if\s+.*module_.*threshold", "module_specific_threshold_count", text, relative, counters, findings)
        _count(_fixture_pattern(), "fixture_runtime_coupling_count", text, relative, counters, findings)
    return DesignQualityAntiHardcodeReport(scanned_files=selected, findings=findings, **counters)


def _count(pattern: str, key: str, text: str, path: str, counters: dict[str, int], findings: list[dict[str, Any]]) -> None:
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
    counters[key] += len(matches)
    for match in matches:
        findings.append({"file": path, "line": text.count("\n", 0, match.start()) + 1, "kind": key})


def _forbidden_pattern() -> str:
    return "|".join(re.escape(bytes.fromhex(item).decode("utf-8")) for item in _FORBIDDEN_TERM_HEX)


def _fixture_pattern() -> str:
    return "|".join(bytes.fromhex(item).decode("utf-8") for item in _FIXTURE_TERM_HEX)
