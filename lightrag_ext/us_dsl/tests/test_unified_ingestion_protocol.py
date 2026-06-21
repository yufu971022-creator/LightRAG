from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.scripts.run_24b0_shadow_router_report import (
    build_sample_shadow_route_plans,
)
from lightrag_ext.us_dsl.unified_ingestion_protocol import (
    DslAwareIngestionOrchestrator,
    UnifiedIngestionRequest,
    safety_invariants,
    serialize_plan,
    serialize_protocol_report,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_shadow_mode_keeps_live_route_raw_and_plans_dsl_candidate() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(_strong_design_request(mode="shadow"))

    assert plan.live_route == "RAW_ONLY"
    assert plan.shadow_candidate_route == "DSL_FULL"
    assert plan.selected_plan_route == "DSL_FULL"
    assert plan.raw_text_plan.enabled is True
    assert plan.dsl_plan.enabled is True
    assert plan.dsl_plan.would_execute_write is False


def test_auto_mode_can_select_dsl_full_without_executing_write() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(_strong_design_request(mode="auto"))

    assert plan.live_route == "DSL_FULL"
    assert plan.selected_plan_route == "DSL_FULL"
    assert plan.metrics.score >= 0.70
    assert plan.dsl_plan.would_execute_write is False
    assert plan.safety_invariants["DSL_WRITE_EXECUTED"] is False


def test_raw_mode_forces_raw_only_even_when_dsl_applicable() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(_strong_design_request(mode="raw"))

    assert plan.live_route == "RAW_ONLY"
    assert plan.selected_plan_route == "RAW_ONLY"
    assert plan.shadow_candidate_route is None
    assert plan.dsl_plan.enabled is False


def test_dsl_mode_returns_partial_when_version_or_type_risk_exists() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(
        UnifiedIngestionRequest(
            document_id="risk-doc",
            mode="dsl",
            metadata={"domain": "RuleManagement"},
            content=(
                "User Story US-9\n"
                "Domain: RuleManagement\n"
                "Business Rule: Fee Rule Version v2 supersedes v1.\n"
                "Acceptance Criteria: Fee Rule Version applies.\n"
                "Evidence: US-9 TU-1 marks review required.\n"
                "Type: TBD for Legacy Override.\n"
            ),
        )
    )

    assert plan.live_route == "DSL_PARTIAL"
    assert plan.metrics.version_risk_count >= 1
    assert plan.metrics.type_issue_count >= 1
    assert plan.metrics.high_risk_object_count >= 1


def test_domain_hit_alone_is_not_enough_for_dsl_full() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(
        UnifiedIngestionRequest(
            document_id="domain-only",
            mode="auto",
            metadata={"domain": "MasterData"},
            content="MasterData appears here without evidence, user story, field definitions, or acceptance criteria.",
        )
    )

    assert plan.profile.recognized_domains == ["MasterData"]
    assert plan.selected_plan_route != "DSL_FULL"
    assert plan.metrics.structure_score < 0.70


def test_parse_failed_for_empty_document() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(
        UnifiedIngestionRequest(document_id="empty", mode="shadow", content="  ")
    )

    assert plan.parse_failed is True
    assert plan.selected_plan_route == "PARSE_FAILED"
    assert "empty_document" in plan.metrics.reasons


def test_generic_graph_fallback_is_separate_and_plan_only() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(
        UnifiedIngestionRequest(
            document_id="fallback",
            mode="auto",
            allow_generic_graph_fallback=True,
            content="Operational note without DSL structure.",
        )
    )

    assert plan.selected_plan_route == "RAW_ONLY"
    assert plan.generic_graph_fallback_plan.enabled is True
    assert plan.generic_graph_fallback_plan.would_execute_write is False
    assert plan.dsl_plan.would_execute_write is False


def test_object_level_risks_are_counted_by_category() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(
        UnifiedIngestionRequest(
            document_id="risk-counts",
            mode="dsl",
            metadata={"domain": "RuleManagement"},
            content="User Story US-10. Business Rule: Version v2 supersedes v1. Type: unknown. Entity: Fee Rule.",
        )
    )

    categories = {risk.risk_category for risk in plan.metrics.object_risks}
    assert "version" in categories
    assert "type" in categories
    assert plan.metrics.object_risk_count == len(plan.metrics.object_risks)


def test_safety_invariants_are_all_false_for_side_effects() -> None:
    invariants = safety_invariants()

    assert invariants["LIVE_UPLOAD_BEHAVIOR_CHANGED"] is False
    assert invariants["LIVE_SHADOW_HOOK_CONNECTED"] is False
    assert invariants["AUTO_WRITE_ROUTING_ENABLED"] is False
    assert invariants["RAW_WRITE_EXECUTED"] is False
    assert invariants["DSL_WRITE_EXECUTED"] is False
    assert invariants["NETWORK_CALLS_EXECUTED"] is False
    assert invariants["MODEL_CALLS_EXECUTED"] is False
    assert invariants["STORAGE_WRITES_EXECUTED"] is False
    assert invariants["LIGHTRAG_CORE_MODIFIED"] is False


def test_plan_serialization_contains_no_execution_flags() -> None:
    plan = DslAwareIngestionOrchestrator().build_plan(_strong_design_request(mode="shadow"))
    payload = serialize_plan(plan)
    rendered = json.dumps(payload, sort_keys=True)

    assert payload["dsl_plan"]["would_execute_write"] is False
    assert payload["raw_text_plan"]["would_execute_write"] is False
    assert "ainsert_custom_kg_called" not in rendered


def test_protocol_report_is_json_serializable() -> None:
    plans = build_sample_shadow_route_plans()
    report = serialize_protocol_report(plans)

    rendered = json.dumps(report, sort_keys=True)
    assert rendered
    assert report["route_distribution"]
    assert len(report["plans"]) >= 4


def test_core_upload_behavior_is_not_connected_by_protocol_module() -> None:
    module_text = (REPO_ROOT / "lightrag_ext/us_dsl/unified_ingestion_protocol.py").read_text(
        encoding="utf-8"
    )

    assert "/documents/upload" not in module_text
    assert ".ainsert(" not in module_text
    assert "ainsert_custom_kg(" not in module_text
    assert "LightRAG(" not in module_text


def _strong_design_request(mode: str) -> UnifiedIngestionRequest:
    return UnifiedIngestionRequest(
        document_id=f"strong-{mode}",
        mode=mode,  # type: ignore[arg-type]
        metadata={"domain": "MasterData"},
        content=(
            "User Story US-2401\n"
            "Domain: MasterData\n"
            "Feature: Bank Status Reference Data\n"
            "Source: US-2401 text unit TU-1 evidence.\n"
            "Acceptance Criteria:\n"
            "Given Query Condition contains account lifecycle inputs.\n"
            "When the customer account is active and KYC is complete.\n"
            "Then Bank Status is set to Eligible.\n"
            "Business Rule: Bank Status is determined by Query Condition.\n"
            "Entity: Bank Status. Entity: Query Condition. Relationship: Bank Status SupportedByEvidence Query Condition.\n"
            "Evidence: US-2401 TU-1 contains the exact source span for both entities.\n"
        ),
    )
