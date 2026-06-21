from __future__ import annotations

from .version_retrieval_types import VersionQueryIntent, VersionQueryRequest

CURRENT_TERMS = ("当前", "现行", "最新", "current", "latest")
HISTORICAL_TERMS = ("历史", "以前", "旧版", "historical", "previous")
COMPARE_TERMS = ("差异", "对比", "compare", "difference")
MIGRATION_TERMS = ("迁移", "初始化", "migration", "initialization")
AS_OF_TERMS = ("截至", "as of")


def detect_version_query_intent(request: VersionQueryRequest) -> VersionQueryIntent:
    if request.explicit_intent:
        return request.explicit_intent
    if request.as_of_time:
        return "AS_OF_TIME"
    text = request.query_text.casefold()
    if any(term.casefold() in text for term in AS_OF_TERMS):
        return "AS_OF_TIME"
    if any(term.casefold() in text for term in COMPARE_TERMS):
        return "COMPARE"
    if any(term.casefold() in text for term in MIGRATION_TERMS):
        return "MIGRATION"
    if any(term.casefold() in text for term in HISTORICAL_TERMS):
        return "HISTORICAL"
    if any(term.casefold() in text for term in CURRENT_TERMS):
        return "CURRENT"
    if request.include_historical:
        return "HISTORICAL"
    if request.require_confirmed_current:
        return "CURRENT"
    return "UNSPECIFIED"
