from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .business_qa_eval import (
    MODE_LIVE,
    MODE_OFFLINE,
    get_business_qa_runtime_flags,
    run_business_qa_ab_eval,
)
from .business_qa_types import (
    BusinessQaAbEvalConfig,
    BusinessQaAbEvalReport,
    BusinessQaCaseResult,
)
from .graph_retrieval_index import build_graph_retrieval_indexes
from .kg_metadata_sidecar import build_graph_insert_sidecar_records
from .kg_test_graph_write import to_lightrag_custom_kg_input
from .lc_business_qa_cases import (
    LCBusinessQaCase,
    default_lc_business_qa_cases,
)
from .lc_graph_subset_builder import (
    ExpandedGraphSubsetResult,
    build_lc_expanded_graph_subset_from_case_pack,
)
from .lc_mini_graph_smoke import (
    LC_MINI_NAMESPACE,
    LcMiniGraphSmokeConfig,
    build_lc_mini_kg_payload,
)


LIVE_LC_QA_ENV = "LIGHTRAG_DSL_RUN_LC_QA_LIVE"
LC_QA_SOURCE = "LC_Acceptable_Bank_US_v1"
EXPANDED_LC_SUBSET_LIMITS = {
    "max_chunks": 15,
    "max_entities": 30,
    "max_relationships": 20,
}

LCBusinessQaCaseResult = BusinessQaCaseResult
LCBusinessQaAbEvalReport = BusinessQaAbEvalReport


def run_lc_business_qa_ab_eval(
    *,
    cases: list[LCBusinessQaCase] | None = None,
    mode: str = MODE_OFFLINE,
    max_cases: int = 10,
    llm_callable=None,
    use_expanded_subset: bool = False,
) -> LCBusinessQaAbEvalReport:
    selected_cases = list(cases or default_lc_business_qa_cases())[:max_cases]
    subset_limits = (
        EXPANDED_LC_SUBSET_LIMITS
        if use_expanded_subset
        else {"max_chunks": 5, "max_entities": 10, "max_relationships": 5}
    )
    subset_result: ExpandedGraphSubsetResult | None = None
    if use_expanded_subset:
        candidate_payload = build_lc_mini_kg_payload(
            LcMiniGraphSmokeConfig(
                max_chunks=100,
                max_entities=100,
                max_relationships=100,
            )
        )
        subset_result = build_lc_expanded_graph_subset_from_case_pack(
            kg_payload=candidate_payload,
            cases=selected_cases,
            max_chunks=subset_limits["max_chunks"],
            max_entities=subset_limits["max_entities"],
            max_relationships=subset_limits["max_relationships"],
        )
        payload = subset_result.subset_payload
        sidecar_records = subset_result.graph_insert_sidecar_records
    else:
        payload = build_lc_mini_kg_payload(
            LcMiniGraphSmokeConfig(
                max_chunks=subset_limits["max_chunks"],
                max_entities=subset_limits["max_entities"],
                max_relationships=subset_limits["max_relationships"],
            )
        )
        custom_kg = to_lightrag_custom_kg_input(payload)
        sidecar_records = build_graph_insert_sidecar_records(
            payload,
            custom_kg,
            namespace=LC_MINI_NAMESPACE,
        )
    indexes = build_graph_retrieval_indexes(payload, sidecar_records)
    config = BusinessQaAbEvalConfig(
        module_name="LC",
        case_pack_name="LC_BUSINESS_QA",
        max_cases=max_cases,
        mode=mode,
        allow_live_llm=mode == MODE_LIVE,
        graph_subset_limits=subset_limits,
        live_env_var=LIVE_LC_QA_ENV,
        source=LC_QA_SOURCE,
    )
    report = run_business_qa_ab_eval(
        selected_cases,
        indexes,
        config=config,
        graph_payload=payload,
        llm_callable=llm_callable,
    )
    if subset_result is not None:
        report.coverage_report = subset_result.coverage_report
        for risk in subset_result.risks:
            if risk not in report.risks:
                report.risks.append(risk)
    return report


def serialize_lc_business_qa_ab_eval_report(
    report: LCBusinessQaAbEvalReport,
) -> dict[str, Any]:
    return asdict(report)


def get_lc_business_qa_runtime_flags() -> dict[str, bool]:
    return get_business_qa_runtime_flags()


__all__ = [
    "EXPANDED_LC_SUBSET_LIMITS",
    "LC_QA_SOURCE",
    "LIVE_LC_QA_ENV",
    "MODE_LIVE",
    "MODE_OFFLINE",
    "LCBusinessQaAbEvalReport",
    "LCBusinessQaCaseResult",
    "get_lc_business_qa_runtime_flags",
    "run_lc_business_qa_ab_eval",
    "serialize_lc_business_qa_ab_eval_report",
]
