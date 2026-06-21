from __future__ import annotations

from .version_issue_index import make_version_issue
from .version_retrieval_types import CurrentVersionResolution, VersionCandidate, VersionIssueRecord

CURRENT_STATUSES = {"CURRENT", "CURRENTBYSINGLEEVIDENCEFORTEST"}
HISTORICAL_STATUSES = {"HISTORICAL", "SUPERSEDED", "DEPRECATED"}
REVIEW_ISSUES = {"VERSION_REVIEW_REQUIRED", "VERSION_CONFLICT", "MULTIPLE_CURRENT", "MULTIPLE_LATEST", "MISSING_VERSION_EVIDENCE"}


class CurrentVersionResolver:
    def resolve(
        self,
        candidates: list[VersionCandidate],
        *,
        issues: list[VersionIssueRecord] | None = None,
        as_of_time: str | None = None,
    ) -> CurrentVersionResolution:
        issues = list(issues or [])
        group_key = candidates[0].version_group_key if candidates else None
        if as_of_time:
            return self._resolve_as_of(candidates, issues=issues, as_of_time=as_of_time, group_key=group_key)
        usable = [item for item in candidates if item.active_contribution and _not_deleted(item)]
        excluded = [item for item in candidates if item not in usable]
        if not usable:
            return _resolution(group_key, "NO_CONFIRMED_CURRENT", None, [], candidates, excluded, issues, ["没有可用于当前检索的候选版本"], False, ["no_active_candidates"])
        missing = [item for item in usable if not _has_evidence(item)]
        if missing:
            generated = make_version_issue(version_group_key=group_key or "", issue_type="MISSING_VERSION_EVIDENCE", reason_code="missing_evidence", member_ids=[item.version_member_id for item in missing], document_version_ids=[item.document_version_id for item in missing])
            return _resolution(group_key, "NO_CONFIRMED_CURRENT", None, [], usable, excluded, [*issues, generated], ["缺少版本证据，不能确认当前规则"], False, ["missing_evidence"])
        if any(item.issue_types for item in usable) or any(item.issue_type in REVIEW_ISSUES for item in issues):
            return _resolution(group_key, "VERSION_REVIEW_REQUIRED", None, [], usable, excluded, issues, ["存在版本待确认或冲突风险"], False, ["version_issue_present"])
        current = [item for item in usable if _status(item) in CURRENT_STATUSES]
        if len(current) > 1:
            issue = make_version_issue(version_group_key=group_key or "", issue_type="MULTIPLE_CURRENT", reason_code="multiple_current", member_ids=[item.version_member_id for item in current], document_version_ids=[item.document_version_id for item in current])
            return _resolution(group_key, "MULTIPLE_CURRENT_CONFLICT", None, [], usable, excluded, [*issues, issue], ["存在多个显式当前版本"], False, ["multiple_current"])
        if len(current) == 1:
            return _resolution(group_key, "CONFIRMED_CURRENT", current[0].version_member_id, current, usable, excluded, issues, [], True, ["unique_explicit_current"])
        latest = [item for item in usable if item.latest_flag is True]
        if len(latest) > 1:
            issue = make_version_issue(version_group_key=group_key or "", issue_type="MULTIPLE_LATEST", reason_code="multiple_latest", member_ids=[item.version_member_id for item in latest], document_version_ids=[item.document_version_id for item in latest])
            return _resolution(group_key, "MULTIPLE_LATEST_CONFLICT", None, [], usable, excluded, [*issues, issue], ["存在多个 latest 标记"], False, ["multiple_latest"])
        if len(latest) == 1:
            return _resolution(group_key, "CONFIRMED_CURRENT", latest[0].version_member_id, latest, usable, excluded, issues, [], True, ["unique_explicit_latest"])
        supersedes_result = _resolve_supersedes_terminal(usable)
        if supersedes_result[0] == "ok":
            terminal = supersedes_result[1]
            return _resolution(group_key, "CONFIRMED_CURRENT", terminal.version_member_id, [terminal], usable, excluded, issues, [], True, ["explicit_supersedes_terminal"])
        if supersedes_result[0] == "conflict":
            issue = make_version_issue(version_group_key=group_key or "", issue_type=str(supersedes_result[2]), reason_code=str(supersedes_result[2]).casefold(), member_ids=[item.version_member_id for item in usable], document_version_ids=[item.document_version_id for item in usable])
            return _resolution(group_key, "SUPERSEDES_CHAIN_CONFLICT", None, [], usable, excluded, [*issues, issue], ["替代关系链存在冲突"], False, [str(supersedes_result[2]).casefold()])
        return _resolution(group_key, "NO_CONFIRMED_CURRENT", None, [], usable, excluded, issues, ["没有足够证据确认当前规则"], False, ["no_confirmed_current"])

    def _resolve_as_of(self, candidates: list[VersionCandidate], *, issues: list[VersionIssueRecord], as_of_time: str, group_key: str | None) -> CurrentVersionResolution:
        usable = [item for item in candidates if item.active_contribution and _not_deleted(item)]
        matches = [item for item in usable if _valid_at(item, as_of_time)]
        if len(matches) == 1 and _has_evidence(matches[0]):
            return _resolution(group_key, "AS_OF_MATCH", matches[0].version_member_id, matches, usable, [], issues, [], True, ["valid_time_match"])
        if len(matches) > 1:
            issue = make_version_issue(version_group_key=group_key or "", issue_type="VALID_TIME_OVERLAP", reason_code="valid_time_overlap", member_ids=[item.version_member_id for item in matches], document_version_ids=[item.document_version_id for item in matches])
            return _resolution(group_key, "VALID_TIME_OVERLAP", None, [], usable, [], [*issues, issue], ["业务有效期存在重叠"], False, ["valid_time_overlap"])
        return _resolution(group_key, "AS_OF_NO_MATCH", None, [], usable, [], issues, ["指定时间没有匹配的业务有效版本"], False, ["as_of_no_match"])


def _resolve_supersedes_terminal(candidates: list[VersionCandidate]) -> tuple[str, VersionCandidate | None, str | None]:
    with_edges = [item for item in candidates if item.supersedes_member_id]
    if not with_edges:
        return "none", None, None
    by_member = {item.version_member_id: item for item in candidates}
    for item in with_edges:
        if item.supersedes_member_id not in by_member:
            return "conflict", None, "SUPERSEDES_TARGET_MISSING"
        if item.review_decision not in {"CONFIRMED_SUPERSEDES", "CONFIRMED"}:
            return "conflict", None, "SUPERSEDES_CHAIN_AMBIGUOUS"
    if _has_cycle(candidates):
        return "conflict", None, "SUPERSEDES_CYCLE"
    superseded = {item.supersedes_member_id for item in with_edges}
    terminals = [item for item in candidates if item.version_member_id not in superseded]
    if len(terminals) != 1:
        return "conflict", None, "SUPERSEDES_CHAIN_AMBIGUOUS"
    return "ok", terminals[0], None


def _has_cycle(candidates: list[VersionCandidate]) -> bool:
    edges = {item.version_member_id: item.supersedes_member_id for item in candidates if item.supersedes_member_id}
    for start in edges:
        seen: set[str] = set()
        node = start
        while node in edges and edges[node]:
            if node in seen:
                return True
            seen.add(node)
            node = str(edges[node])
    return False


def _resolution(group_key, status, current_id, selected, supporting, excluded, issues, warnings, safe, explanation):
    return CurrentVersionResolution(
        version_group_key=group_key,
        resolution_status=status,
        current_candidate_id=current_id,
        selected_candidates=list(selected),
        supporting_candidates=list(supporting),
        excluded_candidates=list(excluded),
        issues=list(issues),
        warnings=list(warnings),
        safe_for_deterministic_answer=safe,
        explanation=list(explanation),
    )


def _has_evidence(item: VersionCandidate) -> bool:
    return bool(item.evidence_excerpt and item.text_unit_id and item.text_hash)


def _status(item: VersionCandidate) -> str:
    return str(item.version_status or "UNKNOWN").replace("_", "").upper()


def _not_deleted(item: VersionCandidate) -> bool:
    return item.document_version_status not in {"DELETED", "TOMBSTONED", "INVALID"}


def _valid_at(item: VersionCandidate, as_of_time: str) -> bool:
    if not item.valid_from:
        return False
    return item.valid_from <= as_of_time and (item.valid_to is None or as_of_time < item.valid_to)
