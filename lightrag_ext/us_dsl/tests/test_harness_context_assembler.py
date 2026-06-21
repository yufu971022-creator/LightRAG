from __future__ import annotations

from lightrag_ext.us_dsl.harness_context_assembler import assemble_harness_context
from lightrag_ext.us_dsl.requirement_scenario_profile import build_requirement_scenario_profile
from lightrag_ext.us_dsl.requirement_scenario_router import route_requirement_scenario
from lightrag_ext.us_dsl.tests.harness_27a_test_helpers import req_many


def test_context_assembler_reuses_trusted_context_pack() -> None:
    req = req_many()
    profile = build_requirement_scenario_profile(req)
    route = route_requirement_scenario(req, profile)
    pack = {"direct_evidence": [{"evidence_id": "ev1", "document_id": "doc", "fact_status": "FACTUAL"}], "issue_warnings": []}
    context = assemble_harness_context(req, profile, route, trusted_context_pack=pack)
    assert context.trusted_context_pack is pack
    assert context.source_evidence[0]["evidence_id"] == "ev1"


def test_candidate_and_issue_are_not_unmarked_facts() -> None:
    req = req_many()
    profile = build_requirement_scenario_profile(req)
    route = route_requirement_scenario(req, profile)
    pack = {
        "direct_evidence": [],
        "factual_candidates": [{"candidate_id": "c1", "trust_tier": "T3_TENTATIVE", "text": "candidate"}],
        "issue_warnings": [{"candidate_id": "i1", "text": "warning"}],
    }
    context = assemble_harness_context(req, profile, route, trusted_context_pack=pack)
    assert context.source_evidence == []
    assert {item["kind"] for item in context.issues_and_warnings} >= {"candidate_not_fact", "issue_warning"}
