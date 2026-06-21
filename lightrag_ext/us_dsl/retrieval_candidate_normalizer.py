from __future__ import annotations

from collections import defaultdict

from .hybrid_retrieval_types import NormalizationReport, RetrievalCandidate


def normalize_retrieval_candidates(
    candidates: list[RetrievalCandidate],
) -> tuple[list[RetrievalCandidate], NormalizationReport]:
    by_channel: dict[str, list[RetrievalCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_channel[candidate.channel].append(candidate)

    normalized: list[RetrievalCandidate] = []
    ranges: dict[str, dict[str, float]] = {}
    for channel, channel_candidates in sorted(by_channel.items()):
        ordered = sorted(channel_candidates, key=lambda item: (-item.raw_score, item.candidate_id))
        raw_scores = [item.raw_score for item in ordered]
        min_score = min(raw_scores) if raw_scores else 0.0
        max_score = max(raw_scores) if raw_scores else 0.0
        ranges[channel] = {"min": min_score, "max": max_score}
        span = max_score - min_score
        for rank, candidate in enumerate(ordered, start=1):
            candidate.channel_rank = rank
            candidate.normalized_score = 1.0 if span == 0 else (candidate.raw_score - min_score) / span
            normalized.append(candidate)

    report = NormalizationReport(
        channel_counts={channel: len(items) for channel, items in by_channel.items()},
        direct_raw_score_addition_used=False,
        score_ranges=ranges,
    )
    return sorted(normalized, key=lambda item: (item.channel, item.channel_rank or 0, item.candidate_id)), report
