from __future__ import annotations

from lightrag_ext.us_dsl.current_version_resolver import CurrentVersionResolver
from lightrag_ext.us_dsl.version_candidate_ranker import VersionCandidateRanker
from lightrag_ext.us_dsl.tests.version_retrieval_test_helpers import current_candidates, issue_index, service
from lightrag_ext.us_dsl.version_retrieval_types import VersionQueryRequest


def _rank(group: str, intent: str, as_of_time: str | None = None):
    candidates = current_candidates(group)
    resolution = CurrentVersionResolver().resolve(candidates, as_of_time=as_of_time)
    return VersionCandidateRanker().rank(candidates, intent=intent, current_resolution=resolution, as_of_time=as_of_time)


def test_current_intent_ranks_confirmed_current_first() -> None:
    ranked = _rank("vg:unique-current", "CURRENT")
    assert ranked[0].candidate.version_member_id == "m:uc:v2"


def test_historical_intent_boosts_historical() -> None:
    ranked = _rank("vg:unique-current", "HISTORICAL")
    assert ranked[0].candidate.version_member_id == "m:uc:v1"


def test_compare_intent_returns_multiple_versions() -> None:
    result = service().retrieve(VersionQueryRequest("compare", explicit_intent="COMPARE", version_group_key="vg:supersedes"))
    assert len(result.selected_candidates) >= 2


def test_migration_intent_keeps_current_historical_and_issues() -> None:
    result = service().retrieve(VersionQueryRequest("migration", explicit_intent="MIGRATION", version_group_key="vg:issue"))
    assert result.selected_candidates
    assert result.version_issues


def test_unspecified_intent_does_not_drop_unknown_versions() -> None:
    result = service().retrieve(VersionQueryRequest("behavior", version_group_key="vg:weak-change"))
    assert result.uncertain_candidates


def test_ranking_is_deterministic() -> None:
    assert _rank("vg:unique-current", "CURRENT") == _rank("vg:unique-current", "CURRENT")


def test_issue_penalty_does_not_hide_version_warning() -> None:
    result = service().retrieve(VersionQueryRequest("current", explicit_intent="CURRENT", version_group_key="vg:issue"))
    assert issue_index().snapshot()["issue_record_count"] == 1
    assert result.warnings
