from __future__ import annotations

from typing import Any

from .version_retrieval_types import VersionAwareRetrievalResult, VersionContext

INTERNAL_CODES = (
    "VERSION_REVIEW_REQUIRED_BLOCKED",
    "policy score",
)


class VersionContextBuilder:
    def build(self, result: VersionAwareRetrievalResult) -> VersionContext:
        current_summary = _current_summary(result)
        historical_summary = _historical_summary(result)
        comparison_summary = _comparison_summary(result)
        uncertainty_summary = _uncertainty_summary(result)
        selected_evidence = _evidence(result.selected_candidates + result.supporting_candidates)
        candidate_table = [_candidate_row(item) for item in result.selected_candidates + result.historical_candidates + result.uncertain_candidates]
        return VersionContext(
            intent=result.intent,
            resolution_status=result.resolution_status,
            safe_for_deterministic_answer=result.safe_for_deterministic_answer,
            current_summary=_sanitize(current_summary),
            historical_summary=_sanitize(historical_summary),
            comparison_summary=_sanitize(comparison_summary),
            uncertainty_summary=_sanitize(uncertainty_summary),
            version_warnings=[_sanitize(item) for item in result.warnings],
            selected_evidence=selected_evidence,
            candidate_table=candidate_table,
            recommended_answer_behavior=_recommended_behavior(result),
        )


def _current_summary(result: VersionAwareRetrievalResult) -> str:
    if result.resolution_status == "CONFIRMED_CURRENT" and result.selected_candidates:
        return "当前规则已确认: " + _label(result.selected_candidates[0])
    return "当前规则未确认"


def _historical_summary(result: VersionAwareRetrievalResult) -> str:
    if not result.historical_candidates:
        return "未返回历史规则"
    return "历史规则: " + ", ".join(_label(item) for item in result.historical_candidates)


def _comparison_summary(result: VersionAwareRetrievalResult) -> str:
    candidates = result.selected_candidates + result.historical_candidates
    if result.intent != "COMPARE" or len(candidates) < 2:
        return "未请求版本对比"
    return "版本对比包含: " + ", ".join(_label(item) for item in candidates[:4])


def _uncertainty_summary(result: VersionAwareRetrievalResult) -> str:
    if result.safe_for_deterministic_answer and not result.version_issues:
        return "无版本不确定提示"
    warnings = result.warnings or ["存在版本待确认"]
    return "; ".join(warnings)


def _recommended_behavior(result: VersionAwareRetrievalResult) -> str:
    if result.resolution_status == "CONFIRMED_CURRENT":
        return "可按当前规则回答，并附带证据。"
    if result.intent == "COMPARE":
        return "按版本分别列规则、证据和差异。"
    if result.intent == "MIGRATION":
        return "同时说明旧规则、新规则和迁移风险。"
    return "不得声明当前规则唯一确定；应列出候选版本、证据和待确认项。"


def _evidence(candidates) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for item in candidates:
        key = (item.version_member_id, item.text_unit_id, item.text_hash)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"version_member_id": item.version_member_id, "text_unit_id": item.text_unit_id, "source_span": item.source_span, "text_hash": item.text_hash, "evidence_excerpt": item.evidence_excerpt})
    return rows


def _candidate_row(item) -> dict[str, Any]:
    return {"version_member_id": item.version_member_id, "rule_version": item.rule_version, "version_status": item.version_status, "latest_flag": item.latest_flag, "document_version_id": item.document_version_id, "evidence_ref": item.text_unit_id}


def _label(item) -> str:
    return item.rule_version or item.version_member_id


def _sanitize(text: str) -> str:
    value = text
    for code in INTERNAL_CODES:
        value = value.replace(code, "版本待确认")
    return value
