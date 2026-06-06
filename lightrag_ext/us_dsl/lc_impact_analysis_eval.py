from __future__ import annotations

from typing import Any

from .graph_retrieval_index import build_graph_retrieval_indexes
from .impact_analysis_eval import (
    MODE_LIVE,
    MODE_OFFLINE,
    get_impact_analysis_runtime_flags,
    run_impact_analysis_ab_eval,
    serialize_impact_analysis_ab_eval_report,
)
from .impact_analysis_types import (
    ImpactAnalysisAbEvalConfig,
    ImpactAnalysisAbEvalReport,
    ImpactAnalysisCase,
)
from .lc_business_qa_eval import EXPANDED_LC_SUBSET_LIMITS
from .lc_graph_subset_builder import build_lc_expanded_graph_subset_from_case_pack
from .lc_impact_analysis_cases import (
    default_lc_impact_analysis_cases,
    serialize_lc_impact_analysis_case,
)
from .lc_mini_graph_smoke import LcMiniGraphSmokeConfig, build_lc_mini_kg_payload


LIVE_LC_IMPACT_ANALYSIS_ENV = "LIGHTRAG_DSL_RUN_LC_IMPACT_ANALYSIS_LIVE"
LC_IMPACT_ANALYSIS_SOURCE = "LC_Acceptable_Bank_US_v1"


def run_lc_impact_analysis_ab_eval(
    *,
    cases: list[ImpactAnalysisCase] | None = None,
    mode: str = MODE_OFFLINE,
    max_cases: int = 6,
    llm_callable=None,
    use_expanded_subset: bool = True,
) -> ImpactAnalysisAbEvalReport:
    selected_cases = list(cases or default_lc_impact_analysis_cases())[:max_cases]
    if use_expanded_subset:
        full_payload = build_lc_mini_kg_payload(
            LcMiniGraphSmokeConfig(
                max_chunks=100,
                max_entities=100,
                max_relationships=100,
            )
        )
        subset = build_lc_expanded_graph_subset_from_case_pack(
            kg_payload=full_payload,
            cases=selected_cases,
            **EXPANDED_LC_SUBSET_LIMITS,
        )
        graph_payload = subset.subset_payload
        sidecar_records = subset.graph_insert_sidecar_records
    else:
        graph_payload = build_lc_mini_kg_payload()
        from .kg_metadata_sidecar import build_graph_insert_sidecar_records
        from .kg_test_graph_write import to_lightrag_custom_kg_input

        sidecar_records = build_graph_insert_sidecar_records(
            graph_payload,
            to_lightrag_custom_kg_input(graph_payload),
            namespace="dsl_test_lc_impact_analysis",
        )
    indexes = build_graph_retrieval_indexes(graph_payload, sidecar_records)
    config = ImpactAnalysisAbEvalConfig(
        module_name="LC",
        case_pack_name="LC_IMPACT_ANALYSIS",
        max_cases=max_cases,
        mode=mode,
        allow_live_llm=mode == MODE_LIVE,
        live_env_var=LIVE_LC_IMPACT_ANALYSIS_ENV,
        source=LC_IMPACT_ANALYSIS_SOURCE,
    )
    return run_impact_analysis_ab_eval(
        cases=selected_cases,
        retrieval_index=indexes,
        config=config,
        graph_payload=graph_payload,
        llm_callable=llm_callable,
    )


def serialize_lc_impact_analysis_case_pack() -> list[dict[str, Any]]:
    return [
        serialize_lc_impact_analysis_case(case)
        for case in default_lc_impact_analysis_cases()
    ]


def get_lc_impact_analysis_runtime_flags() -> dict[str, bool]:
    return get_impact_analysis_runtime_flags()


__all__ = [
    "LC_IMPACT_ANALYSIS_SOURCE",
    "LIVE_LC_IMPACT_ANALYSIS_ENV",
    "MODE_LIVE",
    "MODE_OFFLINE",
    "get_lc_impact_analysis_runtime_flags",
    "run_lc_impact_analysis_ab_eval",
    "serialize_impact_analysis_ab_eval_report",
    "serialize_lc_impact_analysis_case_pack",
]
