from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.business_qa_eval import (
    evaluate_business_case_graph_coverage,
    get_business_qa_runtime_flags,
    serialize_business_qa_graph_coverage_report,
)
from lightrag_ext.us_dsl.business_qa_types import BusinessQaCase
from lightrag_ext.us_dsl.module_qa_case_pack import (
    ModuleQaCasePack,
    validate_module_qa_case_pack,
)
from lightrag_ext.us_dsl.kg_payload_types import (
    DslKgPayload,
    KgChunk,
    KgEntity,
    KgRelationship,
)


def test_generic_business_qa_case_model():
    case = BusinessQaCase(
        case_id="GEN-QA-001",
        module_name="Invoice",
        case_pack_name="invoice-smoke",
        level="L1",
        question="Which rule validates Invoice Amount?",
        expected_behavior="Use only provided evidence.",
        expected_answer_points=["Invoice Amount is validated by Amount Rule."],
        expected_entities=["Invoice Amount", "Amount Rule"],
        expected_relations=["ValidatesField"],
        graph_coverage_expectation="full",
    )

    assert case.module_name == "Invoice"
    assert case.expected_entities == ["Invoice Amount", "Amount Rule"]

    case_pack = ModuleQaCasePack(
        module_name="Invoice",
        case_pack_name="invoice-smoke",
        cases=(case,),
    )
    assert validate_module_qa_case_pack(case_pack) == []


def test_lc_cases_are_case_pack_not_evaluator_logic():
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
    generic_files = [
        Path("lightrag_ext/us_dsl/business_qa_eval.py"),
        Path("lightrag_ext/us_dsl/business_qa_judge.py"),
        Path("lightrag_ext/us_dsl/business_qa_coverage.py"),
    ]
    generic_source = "\n".join(path.read_text(encoding="utf-8") for path in generic_files)

    for term in blocked_terms:
        assert term not in generic_source


def test_generic_graph_coverage_report():
    cases = [
        BusinessQaCase(
            case_id="GEN-QA-001",
            module_name="Invoice",
            case_pack_name="invoice-smoke",
            level="L1",
            question="Which rule validates Invoice Amount?",
            expected_behavior="Use only evidence.",
            expected_answer_points=["Amount Rule validates Invoice Amount."],
            expected_entities=["Invoice Amount", "Amount Rule"],
            expected_relations=["ValidatesField"],
        ),
        BusinessQaCase(
            case_id="GEN-QA-002",
            module_name="Invoice",
            case_pack_name="invoice-smoke",
            level="L1",
            question="Which endpoint posts payment?",
            expected_behavior="Use only evidence.",
            expected_answer_points=["Payment API posts payment."],
            expected_entities=["Payment API"],
            expected_relations=["CallsBackendApi"],
        ),
    ]
    report = evaluate_business_case_graph_coverage(cases, _invoice_payload())

    assert report.case_count == 2
    assert report.covered_case_count == 1
    assert report.full_coverage_count == 1
    assert report.partial_case_count == 0
    assert report.partial_coverage_count == 0
    assert report.uncovered_case_count == 1
    assert report.no_coverage_count == 1
    assert report.missing_entities_by_case["GEN-QA-002"] == ["Payment API"]
    assert report.missing_relations_by_case["GEN-QA-002"] == ["CallsBackendApi"]


def test_no_storage_or_neo4j_in_generic_eval_flags():
    flags = get_business_qa_runtime_flags()

    assert flags["storage_written"] is False
    assert flags["neo4j_connected"] is False


def test_coverage_report_serializable():
    case = BusinessQaCase(
        case_id="GEN-QA-001",
        module_name="Invoice",
        case_pack_name="invoice-smoke",
        level="L1",
        question="Which rule validates Invoice Amount?",
        expected_behavior="Use only evidence.",
        expected_answer_points=["Amount Rule validates Invoice Amount."],
        expected_entities=["Invoice Amount"],
        expected_relations=["ValidatesField"],
    )
    report = evaluate_business_case_graph_coverage([case], _invoice_payload())

    json.dumps(serialize_business_qa_graph_coverage_report(report))


def _invoice_payload() -> DslKgPayload:
    return DslKgPayload(
        chunks=[
            KgChunk(
                content="Invoice Amount must be validated by Amount Rule.",
                source_id="gen-chunk-001",
                file_path=None,
                metadata={"sourceUsId": "GEN-US-001"},
            )
        ],
        entities=[
            KgEntity(
                entity_name="Invoice Amount",
                entity_type="FieldSpec",
                description="Invoice amount field.",
                source_id="gen-chunk-001",
                metadata={"knowledgeStatus": "Candidate"},
            ),
            KgEntity(
                entity_name="Amount Rule",
                entity_type="RuleAtom",
                description="Amount validation rule.",
                source_id="gen-chunk-001",
                metadata={"knowledgeStatus": "Candidate"},
            ),
        ],
        relationships=[
            KgRelationship(
                src_id="Amount Rule",
                tgt_id="Invoice Amount",
                description="Amount Rule validates Invoice Amount.",
                keywords="ValidatesField",
                source_id="gen-chunk-001",
                weight=1.0,
                metadata={"knowledgeStatus": "Candidate"},
            )
        ],
        metadata={},
        issues=[],
        summary={},
    )
