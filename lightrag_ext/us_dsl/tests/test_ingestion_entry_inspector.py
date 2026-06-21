from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.ingestion_entry_inspector import (
    inspect_dsl_extract_usage,
    inspect_dsl_ingestion_chain,
    inspect_original_upload_chain,
    inspect_router_status,
)
from lightrag_ext.us_dsl.scripts.run_ingestion_baseline_inspection import (
    build_ingestion_baseline_payload,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_original_upload_route_is_found() -> None:
    chain = inspect_original_upload_chain(REPO_ROOT)
    route_step = chain.steps[0]

    assert chain.entry_point == "/documents/upload"
    assert route_step.route_or_function == "POST /documents/upload"
    assert route_step.file_path == "lightrag/api/routers/document_routes.py"
    assert route_step.function_name == "upload_to_input_dir"
    assert route_step.line_number > 0


def test_original_call_chain_has_step_evidence() -> None:
    chain = inspect_original_upload_chain(REPO_ROOT)

    assert chain.calls_embedding is True
    assert chain.calls_llm is True
    assert chain.calls_extract_entities is True
    assert chain.calls_ainsert_custom_kg is False
    assert chain.writes_full_docs is True
    assert chain.writes_text_chunks is True
    assert chain.writes_doc_status is True
    assert chain.writes_graph is True
    for step in chain.steps:
        assert step.file_path
        assert step.line_number > 0
        assert step.function_name
        assert step.caller
        assert step.callee


def test_dsl_ingestion_entry_is_found() -> None:
    chain = inspect_dsl_ingestion_chain(REPO_ROOT)
    entry_step = chain.steps[0]

    assert chain.entry_point == "run_dsl_knowledge_ingestion"
    assert entry_step.file_path == "lightrag_ext/us_dsl/dsl_knowledge_ingestion.py"
    assert entry_step.function_name == "run_dsl_knowledge_ingestion"
    assert entry_step.line_number > 0
    assert entry_step.caller == "Explicit DSL tooling/tests/scripts"


def test_dsl_ainsert_custom_kg_call_is_found() -> None:
    chain = inspect_dsl_ingestion_chain(REPO_ROOT)
    writer_step = next(
        step for step in chain.steps if step.entry_id == "dsl-06-local-lightrag-construction"
    )
    core_step = next(
        step for step in chain.steps if step.entry_id == "dsl-07-custom-kg-core-write"
    )

    assert "rag.ainsert_custom_kg" in writer_step.callee
    assert writer_step.file_path == "lightrag_ext/us_dsl/dsl_knowledge_ingestion_writer.py"
    assert writer_step.line_number > 0
    assert writer_step.function_name == "_write_batches_in_working_dir"
    assert core_step.function_name == "ainsert_custom_kg"
    assert core_step.file_path == "lightrag/lightrag.py"
    assert core_step.line_number > 0


def test_current_upload_route_does_not_call_dsl_when_not_present() -> None:
    status = inspect_router_status(REPO_ROOT)

    assert status["upload_calls_dsl"] is False
    assert status["same_file_calls_both_in_upload"] is False


def test_auto_router_detection_is_based_on_code_evidence() -> None:
    status = inspect_router_status(REPO_ROOT)

    assert status["auto_router_exists"] is False
    assert status["domain_auto_dsl"] is False
    assert status["dsl_fallback_to_raw_in_api"] is False


def test_current_state_and_configuration_capability_are_separate() -> None:
    report = build_ingestion_baseline_payload(REPO_ROOT)
    conclusions = report["baseline_conclusions"]

    assert "RAW_AND_DSL_CAN_WRITE_SAME_GRAPH" not in conclusions
    assert "CURRENT_RAW_AND_DSL_SHARE_WORKING_DIR" in conclusions
    assert "CURRENT_RAW_AND_DSL_SHARE_GRAPH_NAMESPACE" in conclusions
    assert "CAPABILITY_RAW_AND_DSL_CAN_TARGET_SAME_GRAPH" in conclusions
    assert conclusions["CURRENT_RAW_AND_DSL_SHARE_WORKING_DIR"]["conclusion"] == "false"
    assert conclusions["CAPABILITY_RAW_AND_DSL_CAN_TARGET_SAME_GRAPH"]["conclusion"] == "true"


def test_dsl_path_does_not_call_original_extract_entities() -> None:
    chain = inspect_dsl_ingestion_chain(REPO_ROOT)
    usage = inspect_dsl_extract_usage(REPO_ROOT)

    assert chain.calls_ainsert_custom_kg is True
    assert chain.calls_extract_entities is False
    assert chain.calls_llm is False
    assert chain.writes_full_docs is False
    assert chain.writes_doc_status is False
    assert usage["run_dsl_chain_calls_ainsert_custom_kg"] is True
    assert usage["run_dsl_chain_calls_extract_entities"] is False
