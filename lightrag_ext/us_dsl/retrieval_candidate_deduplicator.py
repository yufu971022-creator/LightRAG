from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .hybrid_retrieval_types import DeduplicationReport, EvidenceRef, RetrievalCandidate

_CHANNEL_PRIORITY = {
    "PFSS_PATH": 0,
    "PFSS_RELATION": 1,
    "PFSS_ENTITY": 2,
    "RAW_TEXT": 3,
    "VERSION_CONTEXT": 4,
    "ISSUE_SIDECAR": 5,
    "GENERIC_GRAPH": 6,
}


def deduplicate_retrieval_candidates(
    candidates: list[RetrievalCandidate],
) -> tuple[list[RetrievalCandidate], DeduplicationReport]:
    groups: OrderedDict[str, list[RetrievalCandidate]] = OrderedDict()
    for candidate in sorted(candidates, key=lambda item: (_dedup_key(item), item.candidate_id)):
        groups.setdefault(_dedup_key(candidate), []).append(candidate)

    output: list[RetrievalCandidate] = []
    duplicate_groups: list[dict[str, Any]] = []
    generic_overrode_pfss_count = 0
    raw_evidence_preserved = True
    for key, grouped in groups.items():
        winner = sorted(
            grouped,
            key=lambda item: (_CHANNEL_PRIORITY.get(item.channel, 99), -(item.normalized_score or 0), item.candidate_id),
        )[0]
        if winner.channel == "GENERIC_GRAPH" and any(item.channel.startswith("PFSS") for item in grouped):
            generic_overrode_pfss_count += 1
        merged_evidence = _merge_evidence(grouped)
        if any(item.channel == "RAW_TEXT" and item.evidence for item in grouped) and not merged_evidence:
            raw_evidence_preserved = False
        winner.evidence = merged_evidence
        for item in grouped:
            for reason in item.reason_codes:
                if reason not in winner.reason_codes:
                    winner.reason_codes.append(reason)
        output.append(winner)
        if len(grouped) > 1:
            duplicate_groups.append(
                {
                    "dedup_key": key,
                    "winner": winner.candidate_id,
                    "members": [item.candidate_id for item in grouped],
                    "channels": sorted({item.channel for item in grouped}),
                }
            )

    report = DeduplicationReport(
        input_count=len(candidates),
        output_count=len(output),
        duplicate_groups=duplicate_groups,
        generic_overrode_pfss_count=generic_overrode_pfss_count,
        raw_evidence_preserved=raw_evidence_preserved,
        deterministic_path_signature=True,
    )
    return sorted(output, key=lambda item: (_CHANNEL_PRIORITY.get(item.channel, 99), item.candidate_id)), report


def _dedup_key(candidate: RetrievalCandidate) -> str:
    if candidate.stable_identity_key:
        return "identity:" + candidate.stable_identity_key
    if candidate.semantic_relation_id:
        return "relation:" + candidate.semantic_relation_id
    if candidate.semantic_object_id:
        return "object:" + candidate.semantic_object_id
    if candidate.path is not None:
        return "path:" + candidate.path.signature
    if candidate.evidence:
        first = candidate.evidence[0]
        span = ",".join(f"{key}:{value}" for key, value in sorted(first.source_span.items()))
        return f"text:{first.document_version_id}:{first.text_hash}:{span}"
    return "candidate:" + candidate.candidate_id


def _merge_evidence(candidates: list[RetrievalCandidate]) -> list[EvidenceRef]:
    seen: set[tuple[str, str, str, str | None]] = set()
    merged: list[EvidenceRef] = []
    for candidate in candidates:
        for evidence in candidate.evidence:
            key = (
                evidence.document_id,
                evidence.document_version_id,
                evidence.text_unit_id,
                evidence.text_hash,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(evidence)
    return merged
