from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .business_qa_types import BusinessQaCase


@dataclass(frozen=True)
class ModuleQaCasePack:
    module_name: str
    case_pack_name: str
    cases: tuple[BusinessQaCase, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def validate_module_qa_case_pack(case_pack: ModuleQaCasePack) -> list[str]:
    issues: list[str] = []
    if not case_pack.module_name:
        issues.append("module_name is required.")
    if not case_pack.case_pack_name:
        issues.append("case_pack_name is required.")
    if not case_pack.cases:
        issues.append("at least one case is required.")
    for case in case_pack.cases:
        if not case.case_id:
            issues.append("case_id is required.")
        if not case.expected_answer_points:
            issues.append(f"{case.case_id} has no expected_answer_points.")
    return issues


__all__ = ["ModuleQaCasePack", "validate_module_qa_case_pack"]
