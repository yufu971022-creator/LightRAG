from __future__ import annotations

from dataclasses import replace

from lightrag_ext.us_dsl.design_quality_types import DesignQualityCase, ImpactItem, SourceCitation, SupportingFact
from lightrag_ext.us_dsl.functional_qa_executor import execute_functional_qa
from lightrag_ext.us_dsl.impact_analysis_executor import execute_impact_analysis


def qa_case(status: str = "ANSWERED_WITH_CONFIRMED_EVIDENCE") -> DesignQualityCase:
    return DesignQualityCase("T-QA", "SILVER", "FUNCTIONAL_QA", "ONE_TO_MANY", "Question", status)


def impact_case(scenario: str = "ONE_TO_MANY") -> DesignQualityCase:
    return DesignQualityCase("T-IMPACT", "SILVER", "IMPACT_ANALYSIS", scenario, "Requirement", "QUALITY_GATE_PASSED")


def citation() -> SourceCitation:
    return SourceCitation("doc", "docv", "US-1", "tu-1", {"start": 0, "end": 10}, "hash", "excerpt")


def bad_citation() -> SourceCitation:
    return SourceCitation("doc", "docv", "US-1", "tu-1", {"start": 10, "end": 0}, "", "")


def unsupported_fact_output():
    output = execute_functional_qa(qa_case())
    fact = SupportingFact("bad", "s", "p", "o", "bad", "T1_DIRECT", "CONFIRMED_CURRENT", [], "CONFIRMED")
    return replace(output, supporting_facts=[fact])


def candidate_fact_output(kind: str):
    output = execute_functional_qa(qa_case())
    fact = SupportingFact("bad", "s", "p", "o", "bad", "T3_TENTATIVE", "CONFIRMED_CURRENT", ["tu-1"], "CONFIRMED", fact_kind=kind)
    return replace(output, supporting_facts=[fact], source_citations=[citation()])


def impact_with_bad_path():
    output = execute_impact_analysis(impact_case())
    bad = replace(output.direct_impacts[0], evidence_refs=[])
    return replace(output, direct_impacts=[bad])


def duplicate_impact_output():
    output = execute_impact_analysis(impact_case())
    duplicate = replace(output.direct_impacts[0], impact_id="duplicate")
    return replace(output, direct_impacts=[output.direct_impacts[0], duplicate])


def irrelevant_impact_output():
    output = execute_impact_analysis(impact_case())
    bad = ImpactItem(
        "bad",
        "bad-object",
        "bad",
        "FUNCTIONAL_OBJECT",
        "UnknownDomain",
        "feature",
        "unknown_dimension",
        "DIRECT",
        ["a", "b"],
        ["AFFECTS"],
        [output.source_citations[0].text_unit_id],
        "CONFIRMED_CURRENT",
        "CONFIRMED",
        "LOW",
        "bad",
        False,
    )
    return replace(output, direct_impacts=[*output.direct_impacts, bad])
