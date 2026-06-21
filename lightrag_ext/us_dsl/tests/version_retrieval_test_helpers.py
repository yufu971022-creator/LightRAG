from __future__ import annotations

from lightrag_ext.us_dsl.current_version_resolver import CurrentVersionResolver
from lightrag_ext.us_dsl.scripts.run_version_aware_retrieval_smoke import _cand, _fixture_candidates, _fixture_issues
from lightrag_ext.us_dsl.version_candidate_index import VersionCandidateIndex
from lightrag_ext.us_dsl.version_issue_index import VersionIssueIndex
from lightrag_ext.us_dsl.version_retrieval_service import VersionRetrievalService
from lightrag_ext.us_dsl.version_retrieval_types import VersionCandidate


def candidates() -> list[VersionCandidate]:
    return _fixture_candidates()


def candidate_index() -> VersionCandidateIndex:
    return VersionCandidateIndex.from_candidates(candidates())


def issue_index() -> VersionIssueIndex:
    values = candidates()
    return VersionIssueIndex.from_issues(_fixture_issues(values))


def service() -> VersionRetrievalService:
    return VersionRetrievalService(candidate_index=candidate_index(), issue_index=issue_index())


def resolver() -> CurrentVersionResolver:
    return CurrentVersionResolver()


def current_candidates(group_key: str) -> list[VersionCandidate]:
    return candidate_index().current_search_candidates(group_key)


def history_candidates(group_key: str) -> list[VersionCandidate]:
    return candidate_index().history_search_candidates(group_key)


def make_candidate(*args, **kwargs) -> VersionCandidate:
    return _cand(*args, **kwargs)
