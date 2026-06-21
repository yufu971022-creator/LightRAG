from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

BUSINESS_TERMS = (
    "可接受银行",
    "询价",
    "外汇",
    "信用证",
    "账户",
    "现金池",
    "资金计划",
    "付款",
    "融资",
    "票据",
    "Bank Status",
    "Swift Code",
    "Current Handler",
    "Transfer To",
)


@dataclass(frozen=True)
class LocalFullflowAntiHardcodeReport:
    scanned_files: list[str] = field(default_factory=list)
    runtime_module_branch_count: int = 0
    entity_name_specific_rule_count: int = 0
    module_specific_weight_count: int = 0
    fixture_runtime_coupling_count: int = 0
    local_filename_controls_runtime_logic_count: int = 0
    findings: list[dict[str, object]] = field(default_factory=list)


def inspect_local_fullflow_generalization(runtime_roots: list[str | Path]) -> LocalFullflowAntiHardcodeReport:
    files = _runtime_files(runtime_roots)
    findings: list[dict[str, object]] = []
    module_branch_count = 0
    entity_rule_count = 0
    module_weight_count = 0
    fixture_coupling_count = 0
    filename_control_count = 0
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        is_local_eval = path.name.startswith("local_") or path.name == "run_existing_us_local_fullflow.py"
        for node in ast.walk(tree):
            if _is_fixture_import(node):
                fixture_coupling_count += 1
                findings.append({"file": str(path), "type": "fixture_runtime_import", "line": getattr(node, "lineno", 0)})
            if isinstance(node, ast.If):
                test_dump = ast.dump(node.test).casefold()
                body_dump = ast.dump(node).casefold()
                if "module_code" in test_dump and _has_business_literal(node.test):
                    module_branch_count += 1
                    findings.append({"file": str(path), "type": "module_branch", "line": node.lineno})
                if ("entity_name" in test_dump or "original_entity_name" in test_dump) and _has_business_literal(node.test):
                    entity_rule_count += 1
                    findings.append({"file": str(path), "type": "entity_specific_rule", "line": node.lineno})
                if "module_code" in test_dump and _has_business_literal(node.test) and any(
                    token in body_dump for token in ("weight", "score", "rank")
                ):
                    module_weight_count += 1
                    findings.append({"file": str(path), "type": "module_specific_weight", "line": node.lineno})
                if not is_local_eval and any(token in test_dump for token in ("file_name", "filename", "path.name")):
                    filename_control_count += 1
                    findings.append({"file": str(path), "type": "filename_controls_runtime", "line": node.lineno})
    return LocalFullflowAntiHardcodeReport(
        scanned_files=[str(path) for path in files],
        runtime_module_branch_count=module_branch_count,
        entity_name_specific_rule_count=entity_rule_count,
        module_specific_weight_count=module_weight_count,
        fixture_runtime_coupling_count=fixture_coupling_count,
        local_filename_controls_runtime_logic_count=filename_control_count,
        findings=findings,
    )


def _runtime_files(roots: list[str | Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        path = Path(root)
        if path.is_file() and _is_runtime_path(path):
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*.py") if _is_runtime_path(item))
    return sorted(set(files))


def _is_runtime_path(path: Path) -> bool:
    parts = set(path.parts)
    if "tests" in parts or "fixtures" in parts or "artifacts" in parts or "scripts" in parts:
        return False
    if path.name.startswith("test_"):
        return False
    ignored_name_tokens = ("guard", "smoke", "eval", "judge", "cases", "coverage", "test_helpers")
    if any(token in path.stem for token in ignored_name_tokens):
        return False
    return True


def _is_fixture_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any("fixture" in alias.name or "test_helpers" in alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return "fixture" in module or "test_helpers" in module
    return False


def _has_business_literal(node: ast.AST) -> bool:
    terms = {term.casefold() for term in BUSINESS_TERMS}
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if child.value.casefold() in terms:
                return True
    return False
