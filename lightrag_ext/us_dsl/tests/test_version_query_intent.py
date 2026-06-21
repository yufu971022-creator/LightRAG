from __future__ import annotations

import inspect

from lightrag_ext.us_dsl.version_query_intent import detect_version_query_intent
from lightrag_ext.us_dsl.version_retrieval_types import VersionQueryRequest


def test_explicit_intent_has_highest_priority() -> None:
    assert detect_version_query_intent(VersionQueryRequest("current", explicit_intent="COMPARE")) == "COMPARE"


def test_as_of_time_creates_as_of_intent() -> None:
    assert detect_version_query_intent(VersionQueryRequest("rule", as_of_time="2025-01-01")) == "AS_OF_TIME"


def test_generic_current_terms_detect_current_intent() -> None:
    assert detect_version_query_intent(VersionQueryRequest("show current rule")) == "CURRENT"


def test_generic_history_terms_detect_historical_intent() -> None:
    assert detect_version_query_intent(VersionQueryRequest("show historical rule")) == "HISTORICAL"


def test_compare_terms_detect_compare_intent() -> None:
    assert detect_version_query_intent(VersionQueryRequest("compare version difference")) == "COMPARE"


def test_migration_terms_detect_migration_intent() -> None:
    assert detect_version_query_intent(VersionQueryRequest("migration impact")) == "MIGRATION"


def test_unknown_query_remains_unspecified() -> None:
    assert detect_version_query_intent(VersionQueryRequest("how does it behave")) == "UNSPECIFIED"


def test_intent_logic_has_no_business_module_hardcode() -> None:
    source = inspect.getsource(detect_version_query_intent)
    for term in ["可接受银行", "询价", "FX", "现金池", "账户", "付款", "Bank Status", "Swift Code"]:
        assert term not in source
