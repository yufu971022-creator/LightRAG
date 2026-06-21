from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .multi_module_eval_types import EvaluationCase, GoldCaseValidation, GoldValidationReport, MultiModuleManifest


def load_cases_for_manifest(manifest: MultiModuleManifest) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for module in manifest.modules:
        path = Path(module.cases_file)
        if not path.exists():
            continue
        raw_cases = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw_cases, dict):
            raw_cases = raw_cases.get("cases", [])
        for raw in raw_cases:
            payload = dict(raw)
            payload.setdefault("module_code", module.module_code)
            cases.append(parse_evaluation_case(payload))
    return cases


def parse_evaluation_case(raw: dict[str, Any]) -> EvaluationCase:
    return EvaluationCase(
        case_id=str(raw.get("case_id", "")),
        module_code=str(raw.get("module_code", "")),
        task_type=str(raw.get("task_type", "FACT_QA")),
        query=str(raw.get("query", "")),
        strict_scope=bool(raw.get("strict_scope", False)),
        version_intent=raw.get("version_intent"),
        as_of_time=raw.get("as_of_time"),
        gold_source_refs=list(raw.get("gold_source_refs", [])),
        gold_source_us_ids=list(raw.get("gold_source_us_ids", [])),
        gold_text_unit_ids=list(raw.get("gold_text_unit_ids", [])),
        gold_evidence_keywords=list(raw.get("gold_evidence_keywords", [])),
        gold_semantic_object_ids=list(raw.get("gold_semantic_object_ids", [])),
        gold_relation_types=list(raw.get("gold_relation_types", [])),
        gold_required_dimensions=list(raw.get("gold_required_dimensions", [])),
        gold_forbidden_claims=list(raw.get("gold_forbidden_claims", [])),
        gold_forbidden_claims_declared_none=bool(raw.get("gold_forbidden_claims_declared_none", False)),
        gold_version_behavior=raw.get("gold_version_behavior"),
        risk_level=str(raw.get("risk_level", "MEDIUM")),
        review_status=str(raw.get("review_status", "REVIEWED")),
        notes=str(raw.get("notes", "")),
        one_to_n=bool(raw.get("one_to_n", False)),
    )


def validate_gold_cases(manifest: MultiModuleManifest, cases: list[EvaluationCase]) -> GoldValidationReport:
    module_codes = {module.module_code for module in manifest.modules}
    duplicate_ids = sorted([case_id for case_id, count in Counter(case.case_id for case in cases).items() if count > 1])
    results: list[GoldCaseValidation] = []
    for case in cases:
        reasons: list[str] = []
        if not case.case_id:
            reasons.append("MISSING_CASE_ID")
        if case.case_id in duplicate_ids:
            reasons.append("DUPLICATE_CASE_ID")
        if case.module_code not in module_codes:
            reasons.append("UNKNOWN_MODULE_CODE")
        if not case.gold_source_refs:
            reasons.append("MISSING_GOLD_SOURCE_REFS")
        for ref in case.gold_source_refs:
            if not Path(ref).exists():
                reasons.append("UNRESOLVABLE_GOLD_SOURCE_REF")
                break
        if not case.gold_text_unit_ids:
            reasons.append("MISSING_GOLD_TEXT_UNIT_IDS")
        if not case.gold_evidence_keywords:
            reasons.append("MISSING_GOLD_EVIDENCE_KEYWORDS")
        if not case.gold_forbidden_claims and not case.gold_forbidden_claims_declared_none:
            reasons.append("FORBIDDEN_CLAIMS_NOT_DECLARED")
        if not case.gold_version_behavior:
            reasons.append("MISSING_GOLD_VERSION_BEHAVIOR")
        status = "INVALID_GOLD" if reasons else "VALID"
        results.append(GoldCaseValidation(case.case_id, case.module_code, status, reasons))
    invalid = sum(1 for item in results if item.status == "INVALID_GOLD")
    return GoldValidationReport(
        valid_case_count=len(results) - invalid,
        invalid_gold_case_count=invalid,
        case_results=results,
        duplicate_case_ids=duplicate_ids,
    )


def valid_cases(cases: list[EvaluationCase], validation: GoldValidationReport) -> list[EvaluationCase]:
    valid_ids = {item.case_id for item in validation.case_results if item.status == "VALID"}
    return [case for case in cases if case.case_id in valid_ids]
