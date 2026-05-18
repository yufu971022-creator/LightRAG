from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PilotReadiness:
    status: str
    reasons: list[str]
    allowed_scope: list[str] = field(
        default_factory=lambda: [
            "report_only",
            "candidate_review_only",
            "no_graph_write",
            "no_auto_promotion",
        ]
    )
    forbidden_actions: list[str] = field(
        default_factory=lambda: [
            "graph_write",
            "auto_promotion",
            "production_pipeline",
            "formal_fact_write",
        ]
    )


@dataclass
class PilotReportPack:
    report_id: str
    generated_at: str
    module_name: str | None
    document_id: str | None
    source_file: str | None
    dsl_version: str | None
    active_domains: list[str]
    section_type_distribution: dict[str, int]
    feature_count: int
    source_us_count: int
    source_text_unit_count: int
    dsl_aware_chunk_count: int
    vector_payload_count: int
    extraction_payload_count: int
    candidate_entity_count: int
    candidate_relation_count: int
    review_summary: dict[str, Any]
    version_summary: dict[str, Any]
    term_summary: dict[str, Any]
    evidence_summary: dict[str, Any]
    auto_accept_section: list[dict[str, Any]]
    info_only_section: list[dict[str, Any]]
    review_required_section: list[dict[str, Any]]
    blocked_section: list[dict[str, Any]]
    feature_summary: dict[str, Any]
    domain_summary: dict[str, Any]
    generalization_audit_summary: dict[str, Any]
    pilot_readiness: PilotReadiness
    risks: list[str]
    recommendations: list[str]
    next_step: str


__all__ = ["PilotReadiness", "PilotReportPack"]
