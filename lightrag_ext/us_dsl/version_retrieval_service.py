from __future__ import annotations

from .current_version_resolver import CurrentVersionResolver
from .version_candidate_index import VersionCandidateIndex
from .version_candidate_ranker import VersionCandidateRanker
from .version_issue_index import VersionIssueIndex
from .version_query_intent import detect_version_query_intent
from .version_retrieval_types import VersionAwareRetrievalResult, VersionCandidate, VersionQueryRequest


class VersionRetrievalService:
    def __init__(
        self,
        *,
        candidate_index: VersionCandidateIndex,
        issue_index: VersionIssueIndex | None = None,
        current_resolver: CurrentVersionResolver | None = None,
        ranker: VersionCandidateRanker | None = None,
    ) -> None:
        self.candidate_index = candidate_index
        self.issue_index = issue_index or VersionIssueIndex()
        self.current_resolver = current_resolver or CurrentVersionResolver()
        self.ranker = ranker or VersionCandidateRanker()

    def retrieve(self, request: VersionQueryRequest) -> VersionAwareRetrievalResult:
        intent = detect_version_query_intent(request)
        group_key = request.version_group_key or _infer_group_key(self.candidate_index.all_candidates(), request.semantic_object_id)
        include_deleted = intent == "HISTORICAL"
        candidates = self.candidate_index.query_by_version_group_key(group_key, include_deleted=include_deleted) if group_key else self.candidate_index.all_candidates()
        if intent in {"HISTORICAL", "COMPARE", "MIGRATION"}:
            candidates = self.candidate_index.history_search_candidates(group_key) if group_key else candidates
        issues = self.issue_index.query_by_version_group_key(group_key) if group_key else self.issue_index.all_issues()
        current_resolution = self.current_resolver.resolve(candidates, issues=issues, as_of_time=request.as_of_time if intent == "AS_OF_TIME" else None)
        ranked = self.ranker.rank(candidates, intent=intent, current_resolution=current_resolution, issues=[*issues, *current_resolution.issues], as_of_time=request.as_of_time)
        selected, historical, uncertain = _select_by_intent(ranked, intent=intent, current_candidate_id=current_resolution.current_candidate_id)
        warnings = list(dict.fromkeys([*current_resolution.warnings, *(_issue_warnings([*issues, *current_resolution.issues]))]))
        evidence_summary = [
            {"version_member_id": item.version_member_id, "text_unit_id": item.text_unit_id, "text_hash": item.text_hash, "evidence_excerpt": item.evidence_excerpt}
            for item in selected + historical + uncertain
            if item.evidence_excerpt
        ]
        return VersionAwareRetrievalResult(
            request=request,
            intent=intent,
            version_group_key=group_key,
            resolution_status=current_resolution.resolution_status,
            selected_candidates=selected,
            supporting_candidates=current_resolution.supporting_candidates,
            historical_candidates=historical,
            uncertain_candidates=uncertain,
            excluded_candidates=current_resolution.excluded_candidates,
            version_issues=[*issues, *current_resolution.issues],
            warnings=warnings,
            current_candidate_id=current_resolution.current_candidate_id,
            ranking_explanation=[{"version_member_id": item.candidate.version_member_id, "score": item.score, "reasons": item.reasons} for item in ranked],
            evidence_summary=evidence_summary,
            safe_for_deterministic_answer=current_resolution.safe_for_deterministic_answer,
        )


def _infer_group_key(candidates: list[VersionCandidate], semantic_object_id: str | None) -> str | None:
    if semantic_object_id:
        for item in candidates:
            if item.semantic_object_id == semantic_object_id:
                return item.version_group_key
    return candidates[0].version_group_key if candidates else None


def _select_by_intent(ranked, *, intent: str, current_candidate_id: str | None) -> tuple[list[VersionCandidate], list[VersionCandidate], list[VersionCandidate]]:
    ordered = [item.candidate for item in ranked]
    current = [item for item in ordered if item.version_member_id == current_candidate_id]
    historical = [item for item in ordered if str(item.version_status or "").upper() in {"HISTORICAL", "SUPERSEDED", "DEPRECATED"}]
    uncertain = [item for item in ordered if str(item.version_status or "").upper() in {"UNKNOWN", "REVIEWREQUIRED"} or item.issue_types]
    if intent == "COMPARE":
        selected = ordered[: max(2, min(len(ordered), 3))]
    elif intent == "MIGRATION":
        selected = _dedupe_candidates([*(current or ordered[:1]), *historical[:2], *uncertain[:2]])
    elif intent == "HISTORICAL":
        selected = historical or ordered[:2]
    elif intent == "AS_OF_TIME":
        selected = current or ordered[:1]
    else:
        selected = current or ordered[:1]
    return selected, historical, uncertain


def _issue_warnings(issues) -> list[str]:
    if not issues:
        return []
    return ["存在版本待确认或冲突风险"]


def _dedupe_candidates(candidates: list[VersionCandidate]) -> list[VersionCandidate]:
    seen: set[str] = set()
    values: list[VersionCandidate] = []
    for item in candidates:
        if item.version_member_id in seen:
            continue
        seen.add(item.version_member_id)
        values.append(item)
    return values
