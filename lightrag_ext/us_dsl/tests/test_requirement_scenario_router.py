from __future__ import annotations

from lightrag_ext.us_dsl.harness_types import RequirementInput
from lightrag_ext.us_dsl.requirement_scenario_router import route_requirement_scenario
from lightrag_ext.us_dsl.tests.harness_27a_test_helpers import req_insufficient, req_local, req_mixed, req_zero, route_for


def test_missing_retrieval_is_not_automatically_zero_to_one() -> None:
    route = route_for(req_insufficient())
    assert route.selected_scenario is None
    assert route.classification_status == "INSUFFICIENT_EVIDENCE"


def test_cross_domain_risk_prevents_one_to_one_x_overconfidence() -> None:
    route = route_for(req_local(metadata={**req_local().metadata, "affected_domain_count": 3}))
    assert route.selected_scenario is None
    assert route.classification_status == "AMBIGUOUS"


def test_mixed_requirement_is_not_forced_to_one_scenario() -> None:
    route = route_for(req_mixed())
    assert route.selected_scenario is None
    assert route.classification_status == "MIXED"


def test_insufficient_evidence_requires_clarification() -> None:
    route = route_for(req_insufficient())
    assert route.clarification_questions
    assert route.missing_information


def test_manual_override_is_recorded() -> None:
    route = route_for(req_zero(explicit_scenario_override="ONE_TO_MANY"))
    assert route.selected_scenario == "ONE_TO_MANY"
    assert route.classification_status == "MANUAL_OVERRIDE"
    assert route.manual_override_used is True


def test_router_is_deterministic() -> None:
    req = req_zero()
    assert route_for(req) == route_for(req)


def test_router_has_no_module_or_entity_name_rules() -> None:
    req = RequirementInput(
        requirement_id="T-HOLDOUT",
        requirement_text="Random unseen object requests broad impact analysis.",
        module_code="UNKNOWN-RANDOM",
        source_document_refs=["doc"],
        available_design_context=True,
        metadata={
            "primary_change_targets": ["state_transition"],
            "existing_semantic_object_coverage": 0.7,
            "affected_feature_count": 3,
            "affected_domain_count": 2,
            "direct_impact_count": 3,
            "indirect_impact_count": 1,
            "graph_path_count": 2,
            "evidence_sufficiency_score": 0.8,
        },
    )
    assert route_requirement_scenario(req).selected_scenario == "ONE_TO_MANY"
