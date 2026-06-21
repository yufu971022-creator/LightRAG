from __future__ import annotations

from lightrag_ext.us_dsl.design_output_quality_harness import run_design_quality_case, run_design_quality_harness, summarize_quality_results
from lightrag_ext.us_dsl.functional_qa_executor import execute_functional_qa
from lightrag_ext.us_dsl.impact_analysis_executor import execute_impact_analysis
from lightrag_ext.us_dsl.tests.design_quality_27b_test_helpers import impact_case, qa_case


def test_confirmed_evidence_question_is_answerable() -> None:
    result = execute_functional_qa(qa_case())
    assert result.answer_status == "ANSWERED_WITH_CONFIRMED_EVIDENCE"
    assert result.safe_for_business_use


def test_version_conflict_question_requires_warning() -> None:
    result = execute_functional_qa(qa_case("ANSWERED_WITH_VERSION_WARNING"))
    assert result.answer_status == "ANSWERED_WITH_VERSION_WARNING"
    assert result.version_context["version_warnings"]


def test_text_only_question_does_not_invent_graph_relation() -> None:
    result = execute_functional_qa(qa_case("TEXT_ONLY_EVIDENCE"))
    assert result.answer_status == "TEXT_ONLY_EVIDENCE"
    assert result.supporting_relations == []


def test_insufficient_evidence_question_is_not_forced() -> None:
    result = execute_functional_qa(qa_case("INSUFFICIENT_EVIDENCE"))
    assert result.answer_status == "INSUFFICIENT_EVIDENCE"
    assert not result.safe_for_business_use


def test_answer_contains_valid_source_citations() -> None:
    result = execute_functional_qa(qa_case())
    citation = result.source_citations[0]
    assert citation.source_us_id and citation.text_unit_id and citation.text_hash


def test_answer_uses_canonical_identity_with_original_term_trace() -> None:
    result = execute_functional_qa(qa_case())
    assert result.term_identity_context["confirmed_alias_groups"][0]["stable_identity_key"] == "stable.functional.object"


def test_one_to_many_separates_direct_indirect_tentative() -> None:
    result = execute_impact_analysis(impact_case("ONE_TO_MANY"))
    assert result.direct_impacts and result.indirect_impacts and result.tentative_impacts


def test_one_to_many_checks_relevant_domains() -> None:
    result = execute_impact_analysis(impact_case("ONE_TO_MANY"))
    assert set(result.domain_coverage["relevant_domains"]) == {"Workflow", "Integration", "AccessAudit"}


def test_one_to_one_x_does_not_expand_all_domains() -> None:
    result = execute_impact_analysis(impact_case("ONE_TO_ONE_X"))
    assert len(result.domain_coverage["relevant_domains"]) < 10


def test_zero_to_one_does_not_invent_existing_impact() -> None:
    result = execute_impact_analysis(impact_case("ZERO_TO_ONE"))
    assert result.direct_impacts == []
    assert result.indirect_impacts == []


def test_impact_paths_have_evidence() -> None:
    result = execute_impact_analysis(impact_case("ONE_TO_MANY"))
    assert all(item.evidence_refs for item in [*result.direct_impacts, *result.indirect_impacts])


def test_report_is_serializable() -> None:
    import json
    from lightrag_ext.us_dsl.design_quality_types import to_plain_dict

    results = run_design_quality_harness([qa_case(), impact_case()])
    json.dumps(to_plain_dict(summarize_quality_results(results)))


def test_harness_runs_quality_gate_to_passed_state() -> None:
    result = run_design_quality_case(qa_case())
    assert result.final_state == "QUALITY_GATE_PASSED"
