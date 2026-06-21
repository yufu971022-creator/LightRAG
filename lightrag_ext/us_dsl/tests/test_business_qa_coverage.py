from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.business_qa_coverage import (
    evaluate_business_case_graph_coverage,
    serialize_business_qa_graph_coverage_report,
)
from lightrag_ext.us_dsl.business_qa_types import BusinessQaCase
from lightrag_ext.us_dsl.kg_payload_types import (
    DslKgPayload,
    KgChunk,
    KgEntity,
    KgRelationship,
)


def test_graph_coverage_report():
    cases = [
        BusinessQaCase(
            case_id="GEN-COV-001",
            module_name="Order",
            case_pack_name="order-pack",
            level="L1",
            question="Which rule validates Order Amount?",
            expected_behavior="Use evidence only.",
            expected_answer_points=["Amount Rule validates Order Amount."],
            expected_entities=["Order Amount", "Amount Rule"],
            expected_relations=["ValidatesField"],
        ),
        BusinessQaCase(
            case_id="GEN-COV-002",
            module_name="Order",
            case_pack_name="order-pack",
            level="L2",
            question="Which API submits the order?",
            expected_behavior="Use evidence only.",
            expected_answer_points=["Submit API submits the order."],
            expected_entities=["Submit API"],
            expected_relations=["CallsBackendApi"],
        ),
    ]

    report = evaluate_business_case_graph_coverage(
        cases,
        _payload(),
        module_name="Order",
        case_pack_name="order-pack",
    )

    assert report.case_count == 2
    assert report.full_coverage_count == 1
    assert report.partial_coverage_count == 0
    assert report.no_coverage_count == 1
    assert report.missing_entities_by_case["GEN-COV-002"] == ["Submit API"]
    assert report.missing_relations_by_case["GEN-COV-002"] == ["CallsBackendApi"]


def test_generic_coverage_has_no_lc_hardcode():
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
    generic_source = Path("lightrag_ext/us_dsl/business_qa_coverage.py").read_text(
        encoding="utf-8"
    )

    for term in blocked_terms:
        assert term not in generic_source


def test_coverage_report_serializable():
    case = BusinessQaCase(
        case_id="GEN-COV-001",
        module_name="Order",
        case_pack_name="order-pack",
        level="L1",
        question="Which rule validates Order Amount?",
        expected_behavior="Use evidence only.",
        expected_answer_points=["Amount Rule validates Order Amount."],
        expected_entities=["Order Amount"],
        expected_relations=["ValidatesField"],
    )
    report = evaluate_business_case_graph_coverage([case], _payload())

    json.dumps(serialize_business_qa_graph_coverage_report(report))


def _payload() -> DslKgPayload:
    return DslKgPayload(
        chunks=[
            KgChunk(
                content="Amount Rule validates Order Amount.",
                source_id="order-chunk-001",
            )
        ],
        entities=[
            KgEntity(
                entity_name="Order Amount",
                entity_type="FieldSpec",
                description="Order amount field.",
                source_id="order-chunk-001",
            ),
            KgEntity(
                entity_name="Amount Rule",
                entity_type="RuleAtom",
                description="Amount validation rule.",
                source_id="order-chunk-001",
            ),
        ],
        relationships=[
            KgRelationship(
                src_id="Amount Rule",
                tgt_id="Order Amount",
                description="Amount Rule validates Order Amount.",
                keywords="ValidatesField",
                source_id="order-chunk-001",
            )
        ],
    )
