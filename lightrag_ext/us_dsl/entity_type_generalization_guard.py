from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BUSINESS_TERMS = [
    "LCAB",
    "Acceptable Bank",
    "可接受银行",
    "Bank Status",
    "Swift Code",
    "Current Handler",
    "Transfer To",
    "询价项目",
    "询价项目列表",
    "报价",
    "FX",
    "外汇",
    "现金池",
    "账户",
    "资金计划",
    "付款",
]
FIXTURE_REFERENCE_TERMS = ["test_", "acceptable_bank", "inquiry_project", "bank_status"]
RUNTIME_SCAN_FILES = [
    "lightrag_ext/us_dsl/contextual_entity_type_resolver.py",
    "lightrag_ext/us_dsl/product_entity_type_registry.py",
    "lightrag_ext/us_dsl/generic_ner_type_policy.py",
    "lightrag_ext/us_dsl/relation_type_signature_registry.py",
    "lightrag_ext/us_dsl/entity_type_resolution_policy.py",
    "lightrag_ext/us_dsl/entity_type_resolution_types.py",
    "lightrag_ext/us_dsl/entity_type_migration.py",
]


@dataclass(frozen=True)
class HardcodeHit:
    file_path: str
    line_number: int
    term: str
    context: str


@dataclass(frozen=True)
class AntiHardcodeReport:
    files_scanned: list[str]
    business_term_hits: list[HardcodeHit] = field(default_factory=list)
    conditional_business_term_hits: list[HardcodeHit] = field(default_factory=list)
    fixture_reference_hits: list[HardcodeHit] = field(default_factory=list)
    runtime_test_coupling_hits: list[HardcodeHit] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["business_term_hit_count"] = len(self.business_term_hits)
        payload["conditional_business_term_hit_count"] = len(self.conditional_business_term_hits)
        payload["fixture_reference_hit_count"] = len(self.fixture_reference_hits)
        payload["runtime_test_coupling_hit_count"] = len(self.runtime_test_coupling_hits)
        return payload


@dataclass(frozen=True)
class RelationSignatureGeneralizationReport:
    signature_count: int
    name_specific_signature_count: int
    module_specific_signature_count: int
    type_based_signature_count: int
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def scan_runtime_files(root: Path, files: list[str] | None = None) -> AntiHardcodeReport:
    files_to_scan = files or RUNTIME_SCAN_FILES
    business_hits: list[HardcodeHit] = []
    conditional_hits: list[HardcodeHit] = []
    fixture_hits: list[HardcodeHit] = []
    test_hits: list[HardcodeHit] = []
    scanned: list[str] = []
    for rel_path in files_to_scan:
        if _is_test_or_artifact_path(rel_path):
            continue
        path = root / rel_path
        if not path.exists():
            continue
        scanned.append(rel_path)
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=rel_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for term in BUSINESS_TERMS:
                    if term in node.value:
                        business_hits.append(HardcodeHit(rel_path, node.lineno, term, node.value))
                for term in FIXTURE_REFERENCE_TERMS:
                    if term in node.value:
                        hit = HardcodeHit(rel_path, node.lineno, term, node.value)
                        fixture_hits.append(hit)
                        if term.startswith("test_"):
                            test_hits.append(hit)
            if isinstance(node, (ast.If, ast.IfExp, ast.Assert)):
                segment = ast.get_source_segment(text, node) or ""
                for term in BUSINESS_TERMS:
                    if term in segment:
                        conditional_hits.append(HardcodeHit(rel_path, getattr(node, "lineno", 0), term, segment.strip()))
    passed = not business_hits and not conditional_hits and not fixture_hits and not test_hits
    return AntiHardcodeReport(
        files_scanned=scanned,
        business_term_hits=business_hits,
        conditional_business_term_hits=conditional_hits,
        fixture_reference_hits=fixture_hits,
        runtime_test_coupling_hits=test_hits,
        passed=passed,
    )


def summarize_relation_signature_generalization(signatures: dict[str, Any]) -> RelationSignatureGeneralizationReport:
    serialized = str(signatures)
    name_specific = sum(1 for term in BUSINESS_TERMS if term in serialized)
    module_specific = sum(1 for term in ["LCAB", "FX"] if term in serialized)
    signature_count = len(signatures)
    return RelationSignatureGeneralizationReport(
        signature_count=signature_count,
        name_specific_signature_count=name_specific,
        module_specific_signature_count=module_specific,
        type_based_signature_count=signature_count - name_specific - module_specific,
        passed=name_specific == 0 and module_specific == 0,
    )


def _is_test_or_artifact_path(path: str) -> bool:
    parts = Path(path).parts
    return "tests" in parts or "artifacts" in parts or path.endswith("_test.py")
