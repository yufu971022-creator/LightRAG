from __future__ import annotations

import json

from lightrag_ext.us_dsl.graph_answer_types import (
    EvidenceItem,
    GraphAnswerContext,
    GraphPathEvidence,
)
from lightrag_ext.us_dsl.impact_analysis_eval import (
    generate_impact_analysis_deterministic,
    serialize_impact_analysis_ab_eval_report,
)
from lightrag_ext.us_dsl.impact_analysis_judge import (
    compare_impact_analysis_results,
    judge_impact_analysis,
)
from lightrag_ext.us_dsl.impact_analysis_types import (
    DEGRADED,
    IMPROVED,
    MODE_GRAPH_AWARE,
    MODE_TEXT_ONLY,
    ImpactAnalysisAbEvalReport,
    ImpactAnalysisCase,
    ImpactAnalysisJudgement,
    ImpactAnalysisResult,
)


def test_generic_impact_analysis_case_model():
    case = _case(module_name="GEN", entity="Payment Status", relation="HasReportFilter")

    assert case.module_name == "GEN"
    assert case.expected_entities == ["Payment Status"]


def test_text_only_impact_analysis_uses_only_text_context():
    case = _case()
    result = generate_impact_analysis_deterministic(case, _context(MODE_TEXT_ONLY))

    assert result.graph_path_used is False
    assert result.cited_graph_paths == []


def test_graph_aware_impact_analysis_uses_path():
    case = _case()
    result = generate_impact_analysis_deterministic(case, _context(MODE_GRAPH_AWARE))

    assert result.graph_path_used is True
    assert result.cited_graph_paths
    assert "HasReportFilter" in result.impacted_relations


def test_judge_detects_unsupported_claim():
    case = _case()
    context = _context(MODE_GRAPH_AWARE)
    result = ImpactAnalysisResult(
        case_id=case.case_id,
        mode=MODE_GRAPH_AWARE,
        analysis_markdown="NonexistentEntity 会影响流程。EV-graph_aware-01",
        cited_evidence_ids=["EV-graph_aware-01"],
    )

    judgement = judge_impact_analysis(case, result, context)

    assert judgement.unsupported_claim_count > 0


def test_judge_detects_invalid_citation():
    case = _case()
    context = _context(MODE_GRAPH_AWARE)
    result = ImpactAnalysisResult(
        case_id=case.case_id,
        mode=MODE_GRAPH_AWARE,
        analysis_markdown="引用不存在证据。EV-bad-99",
        cited_evidence_ids=["EV-bad-99"],
    )

    judgement = judge_impact_analysis(case, result, context)

    assert judgement.invalid_citation_count > 0


def test_compare_graph_impact_improved():
    case = _case()
    text = _judgement(case, MODE_TEXT_ONLY, score=78, relation_score=2)
    graph = _judgement(case, MODE_GRAPH_AWARE, score=92, relation_score=5)

    comparison = compare_impact_analysis_results(
        case=case,
        text_judgement=text,
        graph_judgement=graph,
        graph_path_used=True,
    )

    assert comparison.improvement_label == IMPROVED


def test_compare_graph_impact_degraded_if_hallucinates():
    case = _case()
    text = _judgement(case, MODE_TEXT_ONLY, score=85, relation_score=3)
    graph = _judgement(case, MODE_GRAPH_AWARE, score=88, relation_score=5, unsupported=1)

    comparison = compare_impact_analysis_results(
        case=case,
        text_judgement=text,
        graph_judgement=graph,
        graph_path_used=True,
    )

    assert comparison.improvement_label == DEGRADED


def test_report_serializable():
    report = ImpactAnalysisAbEvalReport(
        module_name="GEN",
        case_pack_name="GEN_IMPACT",
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
        avg_impact_completeness_delta=0,
        avg_relation_path_delta=0,
        avg_evidence_grounding_delta=0,
        avg_source_span_delta=0,
        avg_unsupported_claim_delta=0,
        graph_path_used_count=0,
        cases_with_invalid_citation=0,
        cases_with_candidate_as_confirmed=0,
        recommended_next_step="TEST",
    )

    json.dumps(serialize_impact_analysis_ab_eval_report(report))


def _case(
    *,
    module_name: str = "GEN",
    entity: str = "Payment Status",
    relation: str = "HasReportFilter",
) -> ImpactAnalysisCase:
    return ImpactAnalysisCase(
        case_id="GEN-IMPACT-001",
        module_name=module_name,
        case_pack_name="GEN_IMPACT",
        level="L1",
        change_request=f"Analyze impact for {entity}.",
        impact_task_type="FIELD_IMPACT",
        expected_impact_dimensions=["Report"],
        expected_entities=[entity],
        expected_relations=[relation],
        expected_domains=["Report"],
        expected_sections=["report_rule"],
        expected_evidence_keywords=[entity],
    )


def _context(mode: str) -> GraphAnswerContext:
    evidence = [
        EvidenceItem(
            evidence_id=f"EV-{mode}-01",
            source_us_id="US-001",
            text_unit_id="tu-1",
            source_span={"start": 0, "end": 20},
            text_hash="hash-1",
            evidence_text="Payment Status is a report filter.",
            feature_key="FeatureA",
            domain_code="Report",
            section_type="report_rule",
            linked_entity="Payment Status",
            linked_relation="HasReportFilter",
            from_graph=mode == MODE_GRAPH_AWARE,
        )
    ]
    paths = (
        [
            GraphPathEvidence(
                path_id="PATH-01",
                nodes=["ReportFeature", "Payment Status"],
                edges=[
                    {
                        "src_id": "ReportFeature",
                        "tgt_id": "Payment Status",
                        "relation_type": "HasReportFilter",
                    }
                ],
                relation_sequence=["HasReportFilter"],
                source_us_ids=["US-001"],
                evidence_texts=["Payment Status is a report filter."],
                source_spans=[{"start": 0, "end": 20}],
                confidence_score=1.0,
            )
        ]
        if mode == MODE_GRAPH_AWARE
        else []
    )
    return GraphAnswerContext(
        query_id="GEN-IMPACT-001",
        query_text="Analyze impact for Payment Status.",
        mode=mode,
        evidence_items=evidence,
        graph_paths=paths,
        expected_entities=["Payment Status"],
        expected_relations=["HasReportFilter"],
        expected_evidence_keywords=["Payment Status"],
    )


def _judgement(
    case: ImpactAnalysisCase,
    mode: str,
    *,
    score: int,
    relation_score: int,
    unsupported: int = 0,
) -> ImpactAnalysisJudgement:
    return ImpactAnalysisJudgement(
        case_id=case.case_id,
        mode=mode,
        score=score,
        result="PASS",
        impact_completeness_score=4,
        relation_path_score=relation_score,
        evidence_grounding_score=5,
        source_span_score=5,
        risk_control_score=5,
        review_readiness_score=5,
        unsupported_claim_count=unsupported,
        invalid_citation_count=0,
    )
