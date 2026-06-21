from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .multi_module_eval_types import EvaluationCase, MultiModuleManifest


@dataclass(frozen=True)
class MultiModuleAntiHardcodeReport:
    scanned_files: list[str] = field(default_factory=list)
    runtime_module_branch_count: int = 0
    entity_name_specific_weight_rule_count: int = 0
    fixture_runtime_coupling_count: int = 0
    holdout_specific_rule_count: int = 0
    findings: list[dict[str, object]] = field(default_factory=list)


def inspect_multi_module_runtime_hardcoding(
    *,
    manifest: MultiModuleManifest,
    cases: list[EvaluationCase],
    runtime_roots: list[str | Path],
) -> MultiModuleAntiHardcodeReport:
    module_codes = {module.module_code for module in manifest.modules}
    holdout_codes = {module.module_code for module in manifest.modules if module.split == "HOLDOUT"}
    entity_names = {item for case in cases for item in case.gold_semantic_object_ids + case.gold_evidence_keywords}
    files = _runtime_files(runtime_roots)
    findings: list[dict[str, object]] = []
    module_branch_count = 0
    entity_weight_count = 0
    fixture_coupling_count = 0
    holdout_rule_count = 0
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if _is_fixture_import(node):
                fixture_coupling_count += 1
                findings.append({"file": str(path), "type": "fixture_runtime_import", "line": getattr(node, "lineno", 0)})
            if isinstance(node, ast.If):
                strings = _string_literals(node.test)
                if strings & entity_names and _body_has_weight_logic(node):
                    entity_weight_count += 1
                    findings.append({"file": str(path), "type": "entity_name_weight_rule", "line": node.lineno})
            if isinstance(node, ast.Compare):
                strings = _string_literals(node)
                if strings & module_codes and _mentions_identifier(node, "module_code"):
                    module_branch_count += 1
                    findings.append({"file": str(path), "type": "module_branch", "line": node.lineno})
                if strings & holdout_codes:
                    holdout_rule_count += 1
                    findings.append({"file": str(path), "type": "holdout_specific_rule", "line": node.lineno})
                if strings & entity_names and _near_weight_logic(node):
                    entity_weight_count += 1
                    findings.append({"file": str(path), "type": "entity_name_weight_rule", "line": node.lineno})
    return MultiModuleAntiHardcodeReport(
        scanned_files=[str(path) for path in files],
        runtime_module_branch_count=module_branch_count,
        entity_name_specific_weight_rule_count=entity_weight_count,
        fixture_runtime_coupling_count=fixture_coupling_count,
        holdout_specific_rule_count=holdout_rule_count,
        findings=findings,
    )


def _runtime_files(roots: list[str | Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        path = Path(root)
        if path.is_file() and path.suffix == ".py" and _is_runtime_path(path):
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*.py") if _is_runtime_path(item))
    return sorted(set(files))


def _is_runtime_path(path: Path) -> bool:
    parts = set(path.parts)
    if "tests" in parts or "fixtures" in parts or "artifacts" in parts:
        return False
    if path.name.startswith("test_"):
        return False
    return True


def _is_fixture_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any("fixture" in alias.name or "test_helpers" in alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return "fixture" in module or "test_helpers" in module
    return False


def _string_literals(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.add(child.value)
    return values


def _mentions_identifier(node: ast.AST, name: str) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id == name:
            return True
        if isinstance(child, ast.Attribute) and child.attr == name:
            return True
    return False


def _near_weight_logic(node: ast.AST) -> bool:
    parent_text = ast.dump(node).casefold()
    return "weight" in parent_text or "score" in parent_text or "rank" in parent_text


def _body_has_weight_logic(node: ast.If) -> bool:
    for child in node.body + node.orelse:
        text = ast.dump(child).casefold()
        if "weight" in text or "score" in text or "rank" in text:
            return True
    return False
