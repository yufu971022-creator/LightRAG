from __future__ import annotations

from typing import Any

from .graph_retrieval_index import build_graph_retrieval_indexes
from .lc_business_qa_eval import EXPANDED_LC_SUBSET_LIMITS
from .lc_graph_subset_builder import build_lc_expanded_graph_subset_from_case_pack
from .lc_mini_graph_smoke import LcMiniGraphSmokeConfig, build_lc_mini_kg_payload
from .lc_us_generation_cases import (
    default_lc_us_generation_cases,
)
from .us_generation_eval import (
    MODE_LIVE,
    MODE_OFFLINE,
    get_us_generation_runtime_flags,
    run_us_generation_ab_eval,
    serialize_us_generation_ab_eval_report,
)
from .us_generation_types import (
    USGenerationAbEvalConfig,
    USGenerationAbEvalReport,
    USGenerationCase,
)


LIVE_LC_US_GENERATION_ENV = "LIGHTRAG_DSL_RUN_LC_US_GENERATION_LIVE"
LC_US_GENERATION_SOURCE = "LC_Acceptable_Bank_US_v1"


def run_lc_us_generation_ab_eval(
    *,
    cases: list[USGenerationCase] | None = None,
    mode: str = MODE_OFFLINE,
    max_cases: int = 8,
    use_expanded_subset: bool = True,
    llm_callable=None,
) -> USGenerationAbEvalReport:
    selected_cases = list(cases or default_lc_us_generation_cases())[:max_cases]
    if use_expanded_subset:
        payload = build_lc_mini_kg_payload(
            LcMiniGraphSmokeConfig(
                max_chunks=100,
                max_entities=100,
                max_relationships=100,
            )
        )
        subset = build_lc_expanded_graph_subset_from_case_pack(
            kg_payload=payload,
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
            namespace="dsl_test_lc_us_generation",
        )
    indexes = build_graph_retrieval_indexes(graph_payload, sidecar_records)
    config = USGenerationAbEvalConfig(
        module_name="LC",
        case_pack_name="LC_US_GENERATION",
        max_cases=max_cases,
        mode=mode,
        allow_live_llm=mode == MODE_LIVE,
        live_env_var=LIVE_LC_US_GENERATION_ENV,
        source=LC_US_GENERATION_SOURCE,
    )
    return run_us_generation_ab_eval(
        cases=selected_cases,
        retrieval_index=indexes,
        config=config,
        graph_payload=graph_payload,
        llm_callable=llm_callable,
    )


def serialize_lc_us_generation_case_pack() -> list[dict[str, Any]]:
    from .lc_us_generation_cases import serialize_lc_us_generation_case

    return [
        serialize_lc_us_generation_case(case)
        for case in default_lc_us_generation_cases()
    ]


def get_lc_us_generation_runtime_flags() -> dict[str, bool]:
    return get_us_generation_runtime_flags()


__all__ = [
    "LC_US_GENERATION_SOURCE",
    "LIVE_LC_US_GENERATION_ENV",
    "MODE_LIVE",
    "MODE_OFFLINE",
    "get_lc_us_generation_runtime_flags",
    "run_lc_us_generation_ab_eval",
    "serialize_lc_us_generation_case_pack",
    "serialize_us_generation_ab_eval_report",
]
