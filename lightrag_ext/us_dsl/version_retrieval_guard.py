from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BUSINESS_TERMS = ["可接受银行", "询价", "FX", "现金池", "账户", "付款", "Bank Status", "Swift Code", "Current Handler", "Transfer To"]
RUNTIME_FILES = [
    "lightrag_ext/us_dsl/version_query_intent.py",
    "lightrag_ext/us_dsl/version_candidate_index.py",
    "lightrag_ext/us_dsl/version_issue_index.py",
    "lightrag_ext/us_dsl/current_version_resolver.py",
    "lightrag_ext/us_dsl/version_candidate_ranker.py",
    "lightrag_ext/us_dsl/version_context_builder.py",
    "lightrag_ext/us_dsl/version_retrieval_service.py",
]


@dataclass(frozen=True)
class VersionRetrievalHardcodeReport:
    files_scanned: list[str]
    runtime_business_hardcode_count: int
    module_specific_version_rule_count: int
    source_us_order_rule_count: int
    document_upload_time_rule_count: int
    hits: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SupersedesGuardReport:
    new_supersedes_created_count: int
    source_us_order_used_for_latest: bool
    document_upload_time_used_for_latest: bool
    weak_change_word_created_supersedes: bool
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def scan_version_retrieval_runtime(root: Path, files: list[str] | None = None) -> VersionRetrievalHardcodeReport:
    files_to_scan = files or RUNTIME_FILES
    hits: list[dict[str, Any]] = []
    source_us_order = 0
    upload_time_order = 0
    module_specific = 0
    scanned: list[str] = []
    for rel_path in files_to_scan:
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
                        hits.append({"file_path": rel_path, "line_number": node.lineno, "term": term, "context": node.value})
            if isinstance(node, (ast.If, ast.Compare, ast.Call, ast.Lambda)):
                segment = ast.get_source_segment(text, node) or ""
                lowered = segment.casefold()
                if "source_us_id" in lowered and any(word in lowered for word in ["latest", "current"]) and any(word in lowered for word in ["max", "sort", ">", "<"]):
                    source_us_order += 1
                if "upload" in lowered and any(word in lowered for word in ["latest", "current"]) and any(word in lowered for word in ["max", "sort", ">", "<"]):
                    upload_time_order += 1
                if "module_code" in lowered and any(term.casefold() in lowered for term in BUSINESS_TERMS):
                    module_specific += 1
    passed = not hits and source_us_order == 0 and upload_time_order == 0 and module_specific == 0
    return VersionRetrievalHardcodeReport(scanned, len(hits), module_specific, source_us_order, upload_time_order, hits, passed)


def build_supersedes_guard_report(*, new_supersedes_created_count: int = 0, source_us_order_used_for_latest: bool = False, document_upload_time_used_for_latest: bool = False, weak_change_word_created_supersedes: bool = False) -> SupersedesGuardReport:
    passed = new_supersedes_created_count == 0 and not source_us_order_used_for_latest and not document_upload_time_used_for_latest and not weak_change_word_created_supersedes
    return SupersedesGuardReport(new_supersedes_created_count, source_us_order_used_for_latest, document_upload_time_used_for_latest, weak_change_word_created_supersedes, passed)
