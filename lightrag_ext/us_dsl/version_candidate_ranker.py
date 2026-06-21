from __future__ import annotations

from dataclasses import dataclass, field

from .version_retrieval_types import CurrentVersionResolution, RankedVersionCandidate, VersionCandidate, VersionIssueRecord, VersionQueryIntent


@dataclass(frozen=True)
class VersionRankerConfig:
    semantic_weight: float = 1.0
    evidence_weight: float = 1.0
    active_contribution_weight: float = 0.5
    current_intent_weight: float = 3.0
    latest_weight: float = 1.5
    valid_time_weight: float = 2.0
    issue_penalty: float = 1.5
    missing_evidence_penalty: float = 2.0
    unknown_penalty: float = 0.75
    historical_current_penalty: float = 0.75
    historical_intent_boost: float = 2.0
    compare_boost: float = 1.0
    migration_balance_boost: float = 1.0
    document_deleted_penalty: float = 2.0
    status_weights: dict[str, float] = field(default_factory=lambda: {"CURRENT": 2.0, "HISTORICAL": 0.2, "SUPERSEDED": 0.2, "UNKNOWN": -0.2, "REVIEWREQUIRED": -1.0})


class VersionCandidateRanker:
    def __init__(self, config: VersionRankerConfig | None = None) -> None:
        self.config = config or VersionRankerConfig()

    def rank(
        self,
        candidates: list[VersionCandidate],
        *,
        intent: VersionQueryIntent,
        current_resolution: CurrentVersionResolution,
        issues: list[VersionIssueRecord] | None = None,
        as_of_time: str | None = None,
    ) -> list[RankedVersionCandidate]:
        issues = list(issues or [])
        ranked = [self._rank_one(item, intent=intent, current_resolution=current_resolution, issues=issues, as_of_time=as_of_time) for item in candidates]
        return sorted(ranked, key=lambda item: (-item.score, _stable_key(item.candidate)))

    def _rank_one(self, candidate: VersionCandidate, *, intent: VersionQueryIntent, current_resolution: CurrentVersionResolution, issues: list[VersionIssueRecord], as_of_time: str | None) -> RankedVersionCandidate:
        score = candidate.semantic_relevance_score * self.config.semantic_weight + candidate.evidence_quality_score * self.config.evidence_weight
        reasons = ["semantic_relevance", "evidence_quality"]
        if candidate.active_contribution:
            score += self.config.active_contribution_weight
            reasons.append("active_contribution")
        status = _status(candidate)
        score += self.config.status_weights.get(status, self.config.status_weights["UNKNOWN"])
        reasons.append(f"status:{status}")
        if candidate.latest_flag is True:
            score += self.config.latest_weight
            reasons.append("explicit_latest")
        if intent in {"CURRENT", "UNSPECIFIED", "AS_OF_TIME"} and current_resolution.current_candidate_id == candidate.version_member_id:
            score += self.config.current_intent_weight
            reasons.append("confirmed_current")
        if intent == "HISTORICAL" and status in {"HISTORICAL", "SUPERSEDED", "DEPRECATED"}:
            score += self.config.historical_intent_boost
            reasons.append("historical_intent_boost")
        if intent == "CURRENT" and status in {"HISTORICAL", "SUPERSEDED", "DEPRECATED"}:
            score -= self.config.historical_current_penalty
            reasons.append("historical_current_penalty")
        if intent == "COMPARE":
            score += self.config.compare_boost
            reasons.append("compare_keep_candidate")
        if intent == "MIGRATION":
            score += self.config.migration_balance_boost
            reasons.append("migration_keep_candidate")
        if intent == "AS_OF_TIME" and as_of_time and _valid_at(candidate, as_of_time):
            score += self.config.valid_time_weight
            reasons.append("valid_time_match")
        if not candidate.evidence_excerpt or not candidate.text_unit_id:
            score -= self.config.missing_evidence_penalty
            reasons.append("missing_evidence_penalty")
        if candidate.issue_types or any(candidate.version_member_id in issue.member_ids for issue in issues):
            score -= self.config.issue_penalty
            reasons.append("version_issue_penalty")
        if status in {"UNKNOWN", "REVIEWREQUIRED"}:
            score -= self.config.unknown_penalty
            reasons.append("unknown_version_penalty")
        if candidate.document_version_status == "DELETED":
            score -= self.config.document_deleted_penalty
            reasons.append("deleted_projection_penalty")
        return RankedVersionCandidate(candidate=candidate, score=round(score, 6), reasons=reasons)


def _status(candidate: VersionCandidate) -> str:
    return str(candidate.version_status or "UNKNOWN").replace("_", "").upper()


def _valid_at(candidate: VersionCandidate, as_of_time: str) -> bool:
    return bool(candidate.valid_from and candidate.valid_from <= as_of_time and (candidate.valid_to is None or as_of_time < candidate.valid_to))


def _stable_key(candidate: VersionCandidate) -> tuple[str, str, str]:
    return (candidate.stable_identity_key or candidate.semantic_object_id, candidate.version_member_id, candidate.document_version_id)
