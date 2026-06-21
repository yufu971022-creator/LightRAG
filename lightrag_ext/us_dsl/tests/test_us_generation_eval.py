from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.graph_answer_types import EvidenceItem, GraphAnswerContext
from lightrag_ext.us_dsl.graph_retrieval_types import MODE_GRAPH_AWARE
from lightrag_ext.us_dsl.us_generation_eval import (
    generate_us_deterministic,
    serialize_us_generation_ab_eval_report,
)
from lightrag_ext.us_dsl.us_generation_judge import judge_us_generation
from lightrag_ext.us_dsl.us_generation_types import (
    FAIL,
    USGenerationAbEvalReport,
    USGenerationCase,
    USGenerationResult,
)


def test_generic_us_generation_case_model():
    case = _case()

    assert case.module_name == "Invoice"
    assert case.generation_task_type == "FIELD_CHANGE_US"
    assert "field_specs" in case.expected_us_sections


def test_lc_us_generation_cases_are_case_pack_not_evaluator_logic():
    blocked_terms = [
        "LCAB",
        "Acceptable Bank",
        "可接受银行",
        "Bank Status",
        "Swift Code",
        "Bank Internal Code",
        "Transfer To",
        "Bank Default Confirmation",
        "eflowNum",
        "Suggested Rating",
    ]
    generic_source = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in [
            "lightrag_ext/us_dsl/us_generation_eval.py",
            "lightrag_ext/us_dsl/us_generation_judge.py",
        ]
    )

    for term in blocked_terms:
        assert term not in generic_source


def test_us_output_has_required_structure():
    result = generate_us_deterministic(_case(), _context(MODE_GRAPH_AWARE))

    assert "# Generate invoice amount validation" in result.generated_us_markdown
    assert "## As a / I Want / So That" in result.generated_us_markdown
    assert "## Given / When / Then" in result.generated_us_markdown
    assert "## Acceptance Criteria" in result.generated_us_markdown
    assert "## Source Evidence" in result.generated_us_markdown


def test_judge_detects_missing_required_section():
    case = _case()
    result = USGenerationResult(
        case_id=case.case_id,
        mode=MODE_GRAPH_AWARE,
        generated_us_markdown="## Source Evidence\n- EV-graph_aware-01",
        generated_sections=["source_evidence"],
        cited_evidence_ids=["EV-graph_aware-01"],
    )

    judgement = judge_us_generation(case, result, _context(MODE_GRAPH_AWARE))

    assert "field_specs" in judgement.missing_expected_sections
    assert judgement.score < 85


def test_judge_detects_unsupported_claim():
    case = _case()
    result = USGenerationResult(
        case_id=case.case_id,
        mode=MODE_GRAPH_AWARE,
        generated_us_markdown="NonexistentEntity is required. EV-graph_aware-01",
        generated_sections=list(case.expected_us_sections),
        cited_evidence_ids=["EV-graph_aware-01"],
    )

    judgement = judge_us_generation(case, result, _context(MODE_GRAPH_AWARE))

    assert judgement.unsupported_claim_count > 0


def test_judge_detects_invalid_citation():
    case = _case()
    result = USGenerationResult(
        case_id=case.case_id,
        mode=MODE_GRAPH_AWARE,
        generated_us_markdown="Invoice Amount is required. EV-bad-99",
        generated_sections=list(case.expected_us_sections),
        cited_evidence_ids=["EV-bad-99"],
    )

    judgement = judge_us_generation(case, result, _context(MODE_GRAPH_AWARE))

    assert judgement.invalid_citation_count == 1
    assert judgement.result == FAIL


def test_judge_detects_candidate_as_confirmed():
    case = _case()
    result = USGenerationResult(
        case_id=case.case_id,
        mode=MODE_GRAPH_AWARE,
        generated_us_markdown="This Candidate is Confirmed. EV-graph_aware-01",
        generated_sections=list(case.expected_us_sections),
        cited_evidence_ids=["EV-graph_aware-01"],
    )

    judgement = judge_us_generation(case, result, _context(MODE_GRAPH_AWARE))

    assert judgement.candidate_as_confirmed_count == 1
    assert judgement.result == FAIL


def test_report_serializable():
    report = USGenerationAbEvalReport(
        module_name="Invoice",
        case_pack_name="invoice-us-pack",
        case_count=0,
        text_only_pass_count=0,
        graph_aware_pass_count=0,
        improved_count=0,
        same_count=0,
        degraded_count=0,
        inconclusive_count=0,
        avg_text_score=0,
        avg_graph_score=0,
        avg_score_delta=0,
        avg_evidence_grounding_delta=0,
        avg_source_span_delta=0,
        avg_unsupported_claim_delta=0,
        avg_structure_completeness_delta=0,
        avg_business_rule_coverage_delta=0,
        avg_review_readiness_delta=0,
        graph_path_used_count=0,
        accept_as_is_count=0,
        accept_with_minor_edits_count=0,
        need_major_revision_count=0,
        reject_count=0,
        recommended_next_step="test",
    )

    json.dumps(serialize_us_generation_ab_eval_report(report))


def _case() -> USGenerationCase:
    return USGenerationCase(
        case_id="GEN-US-001",
        module_name="Invoice",
        case_pack_name="invoice-us-pack",
        level="L1",
        user_request="Generate invoice amount validation",
        generation_task_type="FIELD_CHANGE_US",
        expected_us_sections=[
            "role_goal_value",
            "given_when_then",
            "field_specs",
            "business_rules",
            "acceptance_criteria",
            "source_evidence",
        ],
        expected_entities=["Invoice Amount", "Amount Rule"],
        expected_relations=["ValidatesField"],
        expected_evidence_keywords=["required"],
        forbidden_claims=["auto approve"],
        grading_notes="Use evidence only.",
        graph_coverage_expectation="full",
    )


def _context(mode: str) -> GraphAnswerContext:
    return GraphAnswerContext(
        query_id="GEN-US-001",
        query_text="Generate invoice amount validation",
        mode=mode,
        evidence_items=[
            EvidenceItem(
                evidence_id=f"EV-{mode}-01",
                source_us_id="GEN-US-SRC-001",
                text_unit_id="TU-001",
                source_span={"start": 0, "end": 10},
                text_hash="hash-001",
                evidence_text="Invoice Amount is required and validated by Amount Rule.",
                feature_key="InvoiceFeature",
                domain_code="Invoice",
                section_type="business_rule",
                linked_entity="Invoice Amount",
                linked_relation="ValidatesField",
                from_graph=mode == MODE_GRAPH_AWARE,
            )
        ],
        expected_entities=["Invoice Amount", "Amount Rule"],
        expected_relations=["ValidatesField"],
        expected_evidence_keywords=["required"],
    )
