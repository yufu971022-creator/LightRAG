from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class IssueSummary:
    unsupported_claim_count: int = 0
    invalid_citation_count: int = 0
    candidate_as_confirmed_count: int = 0
    info_only_as_fact_count: int = 0
    missing_evidence_count: int = 0
    version_review_required_count: int = 0
    forbidden_relation_count: int = 0
    dangling_relationship_count: int = 0
    sidecar_mismatch_count: int = 0
    graph_write_failure_count: int = 0
    retrieval_degraded_count: int = 0
    qa_degraded_count: int = 0
    us_generation_degraded_count: int = 0
    impact_analysis_degraded_count: int = 0


@dataclass(frozen=True)
class OptimizationBacklogItem:
    issue_type: str
    severity: str
    description: str
    affected_cases: list[str] = field(default_factory=list)
    recommended_fix: str = ""
    owner_hint: str = ""
    next_block_hint: str = ""


@dataclass
class E2EGraphPipelineReport:
    source: str
    namespace: str
    enabled: bool
    skipped: bool
    skip_reason: str | None
    source_us_count: int
    source_text_unit_count: int
    kg_payload_chunk_count: int
    kg_payload_entity_count: int
    kg_payload_relationship_count: int
    approved_for_test_graph_count: int
    blocked_from_graph_count: int
    block_reason_distribution: dict[str, int]
    custom_kg_chunk_count: int
    custom_kg_entity_count: int
    custom_kg_relationship_count: int
    sidecar_record_count: int
    sidecar_alignment_passed: bool
    governance_passed: bool
    graph_write_attempted: bool
    graph_write_succeeded: bool
    neo4j_connected: bool
    production_write: bool
    formal_graph_written: bool
    rollback_passed: bool
    cleanup_passed: bool
    retrieval_eval_summary: dict[str, Any] = field(default_factory=dict)
    business_qa_eval_summary: dict[str, Any] = field(default_factory=dict)
    us_generation_eval_summary: dict[str, Any] = field(default_factory=dict)
    impact_analysis_eval_summary: dict[str, Any] = field(default_factory=dict)
    version_issue_triage_summary: dict[str, Any] = field(default_factory=dict)
    version_review_required_before: int = 0
    version_review_required_after: int = 0
    version_review_required_reduction: int = 0
    version_safe_for_test_count: int = 0
    version_formal_blocked_count: int = 0
    true_version_review_required_count: int = 0
    unsafe_supersedes_blocked_count: int = 0
    issue_summary: IssueSummary = field(default_factory=IssueSummary)
    optimization_backlog: list[OptimizationBacklogItem] = field(default_factory=list)
    recommended_next_step: str = ""
    risks: list[str] = field(default_factory=list)
    llm_called: bool = False
    test_only: bool = True


def serialize_e2e_graph_pipeline_report(report: E2EGraphPipelineReport) -> dict[str, Any]:
    return asdict(report)


__all__ = [
    "E2EGraphPipelineReport",
    "IssueSummary",
    "OptimizationBacklogItem",
    "serialize_e2e_graph_pipeline_report",
]
