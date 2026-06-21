from __future__ import annotations

from lightrag_ext.us_dsl.tests.version_retrieval_test_helpers import service
from lightrag_ext.us_dsl.version_retrieval_types import VersionQueryRequest


def test_no_confirmed_current_returns_candidates_and_warning() -> None:
    result = service().retrieve(VersionQueryRequest("current", explicit_intent="CURRENT", version_group_key="vg:weak-change"))
    assert result.resolution_status == "NO_CONFIRMED_CURRENT"
    assert result.selected_candidates
    assert result.warnings
