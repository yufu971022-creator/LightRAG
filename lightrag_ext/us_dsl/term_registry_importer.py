from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

from .term_normalization_types import TermMappingRecord, TermScope
from .term_registry import TermRegistry

CSV_COLUMNS = [
    "module_code",
    "system_name",
    "domain_code",
    "feature_key",
    "object_type",
    "source_term",
    "canonical_term",
    "source_language",
    "canonical_language",
    "synonym_type",
    "confidence",
    "status",
    "requires_scope",
    "effective_from",
    "effective_to",
    "owner",
    "comments",
]

XLSX_IMPORT_STATUS = "AVAILABLE" if importlib.util.find_spec("openpyxl") else "DEFERRED_NO_EXISTING_DEPENDENCY"


def import_term_registry_csv(path: str | Path, *, registry_version: str = "25A-0", allow_conflicts: bool = False) -> TermRegistry:
    registry = TermRegistry(registry_version=registry_version, allow_conflicts=allow_conflicts)
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=1):
            registry.add(_record_from_row(row, index=index, registry_version=registry_version))
    return registry


def write_term_registry_template(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
    return target


def write_fixture_registry_csv(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = fixture_rows()
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return target


def fixture_rows() -> list[dict[str, str]]:
    base = {"module_code": "MOD-PRODUCT", "system_name": "CoreSystem", "feature_key": "PaymentFeature", "owner": "fixture", "comments": "25A-0 fixture"}
    return [
        {**base, "domain_code": "Integration", "object_type": "FieldSpec", "source_term": "SWIFTCODE", "canonical_term": "Swift Code", "source_language": "en", "canonical_language": "en", "synonym_type": "WHITESPACE_VARIANT", "confidence": "0.99", "status": "CONFIRMED", "requires_scope": "false", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Integration", "object_type": "FieldSpec", "source_term": "SWIFT CODE", "canonical_term": "Swift Code", "source_language": "en", "canonical_language": "en", "synonym_type": "WHITESPACE_VARIANT", "confidence": "0.99", "status": "CONFIRMED", "requires_scope": "false", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Integration", "object_type": "FieldSpec", "source_term": "swift-code", "canonical_term": "Swift Code", "source_language": "en", "canonical_language": "en", "synonym_type": "PUNCTUATION_VARIANT", "confidence": "0.98", "status": "CONFIRMED", "requires_scope": "false", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Integration", "object_type": "FieldSpec", "source_term": "swift_code", "canonical_term": "Swift Code", "source_language": "en", "canonical_language": "en", "synonym_type": "PUNCTUATION_VARIANT", "confidence": "0.98", "status": "CONFIRMED", "requires_scope": "false", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Workflow", "feature_key": "HandlerFeature", "object_type": "RolePermission", "source_term": "当前处理人", "canonical_term": "Current Handler", "source_language": "zh", "canonical_language": "en", "synonym_type": "TRANSLATION", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Workflow", "feature_key": "HandlerFeature", "object_type": "RolePermission", "source_term": "Current Handler", "canonical_term": "Current Handler", "source_language": "en", "canonical_language": "en", "synonym_type": "CASE_VARIANT", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Ledger", "feature_key": "BankStatusFeature", "object_type": "FieldSpec", "source_term": "状态", "canonical_term": "Bank Status", "source_language": "zh", "canonical_language": "en", "synonym_type": "TRANSLATION", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Ledger", "feature_key": "BankStatusFeature", "object_type": "FieldSpec", "source_term": "Status", "canonical_term": "Bank Status", "source_language": "en", "canonical_language": "en", "synonym_type": "BUSINESS_ALIAS", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Ledger", "feature_key": "BankStatusFeature", "object_type": "FieldSpec", "source_term": "银行状态", "canonical_term": "Bank Status", "source_language": "zh", "canonical_language": "en", "synonym_type": "TRANSLATION", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "MonitoringReport", "feature_key": "MonitoringSearch", "object_type": "ReportSpec", "source_term": "查询", "canonical_term": "Search", "source_language": "zh", "canonical_language": "en", "synonym_type": "TRANSLATION", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "MonitoringReport", "feature_key": "MonitoringSearch", "object_type": "ReportSpec", "source_term": "Search", "canonical_term": "Search", "source_language": "en", "canonical_language": "en", "synonym_type": "CASE_VARIANT", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Ledger", "feature_key": "BankStatusFeature", "object_type": "FieldSpec", "source_term": "Bank Status", "canonical_term": "Bank Status", "source_language": "en", "canonical_language": "en", "synonym_type": "CASE_VARIANT", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Workflow", "feature_key": "ApprovalFeature", "object_type": "FieldSpec", "source_term": "Approval Status", "canonical_term": "Approval Status", "source_language": "en", "canonical_language": "en", "synonym_type": "CASE_VARIANT", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Workflow", "feature_key": "TaskFeature", "object_type": "FieldSpec", "source_term": "Task Status", "canonical_term": "Task Status", "source_language": "en", "canonical_language": "en", "synonym_type": "CASE_VARIANT", "confidence": "1.0", "status": "CONFIRMED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Workflow", "feature_key": "CandidateFeature", "object_type": "FieldSpec", "source_term": "Handler", "canonical_term": "Current Handler", "source_language": "en", "canonical_language": "en", "synonym_type": "BUSINESS_ALIAS", "confidence": "0.8", "status": "CANDIDATE", "requires_scope": "true", "effective_from": "", "effective_to": ""},
        {**base, "domain_code": "Workflow", "feature_key": "RejectedFeature", "object_type": "FieldSpec", "source_term": "Owner", "canonical_term": "Current Handler", "source_language": "en", "canonical_language": "en", "synonym_type": "BUSINESS_ALIAS", "confidence": "0.4", "status": "REJECTED", "requires_scope": "true", "effective_from": "", "effective_to": ""},
    ]


def _record_from_row(row: dict[str, str], *, index: int, registry_version: str) -> TermMappingRecord:
    scope = TermScope(
        system_name=_blank(row.get("system_name")),
        module_code=_blank(row.get("module_code")),
        domain_code=_blank(row.get("domain_code")),
        feature_key=_blank(row.get("feature_key")),
        object_type=_blank(row.get("object_type")),
        language_code=_blank(row.get("source_language")),
    )
    source = row["source_term"].strip()
    canonical = row["canonical_term"].strip()
    return TermMappingRecord(
        term_mapping_id=f"term:{registry_version}:{index:04d}",
        source_term=source,
        canonical_term=canonical,
        source_language=_blank(row.get("source_language")),
        canonical_language=_blank(row.get("canonical_language")),
        synonym_type=(row.get("synonym_type") or "BUSINESS_ALIAS").strip().upper(),  # type: ignore[arg-type]
        scope=scope,
        confidence=float(row.get("confidence") or 0.0),
        status=(row.get("status") or "CANDIDATE").strip().upper(),  # type: ignore[arg-type]
        mapping_source="CONFIG",
        requires_scope=_truthy(row.get("requires_scope")),
        effective_from=_blank(row.get("effective_from")),
        effective_to=_blank(row.get("effective_to")),
        owner=_blank(row.get("owner")),
        comments=_blank(row.get("comments")),
        registry_version=registry_version,
    )


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _blank(value: str | None) -> str | None:
    value = str(value or "").strip()
    return value or None
