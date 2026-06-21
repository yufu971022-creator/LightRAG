from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from lightrag_ext.us_dsl.ingestion_baseline_types import to_plain_dict
from lightrag_ext.us_dsl.runtime_baseline_probe import probe_runtime_baseline
from lightrag_ext.us_dsl.scripts.run_ingestion_baseline_inspection import (
    _core_diff_check,
    _fake_real_embedding_mix_risk,
    _render_markdown,
    build_ingestion_baseline_payload,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PREFIXES = ("LLM_", "EMBEDDING_", "LIGHTRAG_")
ENV_KEYS = {
    "WORKING_DIR",
    "WORKSPACE",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_EMBEDDING_API_KEY",
    "GEMINI_API_KEY",
    "JINA_API_KEY",
    "VOYAGE_API_KEY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
}
REQUIRED_CONCLUSION_FIELDS = {
    "CURRENT_RAW_AND_DSL_SHARE_WORKING_DIR",
    "CURRENT_RAW_AND_DSL_SHARE_GRAPH_NAMESPACE",
    "CAPABILITY_RAW_AND_DSL_CAN_TARGET_SAME_GRAPH",
    "CURRENT_UPLOAD_ROUTE_CALLS_DSL",
    "CURRENT_AUTO_INGESTION_ROUTER_EXISTS",
    "CURRENT_DSL_PATH_CALLS_AINSERT_CUSTOM_KG",
    "CURRENT_DSL_PATH_CALLS_ORIGINAL_EXTRACT_ENTITIES",
    "CURRENT_RAW_PATH_CALLS_LLM_EXTRACTION",
    "CURRENT_FAKE_AND_REAL_EMBEDDING_MIX_DETECTED",
    "FAKE_AND_REAL_EMBEDDING_MIX_RISK",
}


def test_runtime_probe_masks_all_secrets(tmp_path, monkeypatch) -> None:
    _clear_relevant_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "LLM_BINDING=openai",
                "LLM_BINDING_HOST=https://api.openai.com/v1/private-path",
                "LLM_BINDING_API_KEY=llm-secret-value",
                "LLM_MODEL=gpt-5.4-mini",
                "ENABLE_LLM_CACHE_FOR_EXTRACT=true",
                "EMBEDDING_BINDING=openai",
                "EMBEDDING_BINDING_HOST=https://api.openai.com/v1/private-path",
                "EMBEDDING_BINDING_API_KEY=embedding-secret-value",
                "EMBEDDING_MODEL=text-embedding-3-large",
                "EMBEDDING_DIM=3072",
                "EMBEDDING_TOKEN_LIMIT=8192",
                "LIGHTRAG_KV_STORAGE=JsonKVStorage",
                "LIGHTRAG_DOC_STATUS_STORAGE=JsonDocStatusStorage",
                "LIGHTRAG_GRAPH_STORAGE=NetworkXStorage",
                "LIGHTRAG_VECTOR_STORAGE=NanoVectorDBStorage",
            ]
        ),
        encoding="utf-8",
    )

    baseline = probe_runtime_baseline(tmp_path)
    plain = to_plain_dict(baseline)
    rendered_json = json.dumps(plain, sort_keys=True)
    report = build_ingestion_baseline_payload(REPO_ROOT)
    rendered_md = _render_markdown(report)
    command_log = REPO_ROOT / "artifacts/block_24a0_ingestion_baseline/command_log.txt"
    rendered_log = command_log.read_text(encoding="utf-8") if command_log.exists() else ""

    assert plain["embedding"]["credential_configured"] is True
    assert plain["embedding"]["credential_fingerprint"].startswith("sha256:")
    assert plain["llm"]["credential_configured"] is True
    assert plain["llm"]["credential_fingerprint"].startswith("sha256:")
    combined = "\n".join([rendered_json, rendered_md, rendered_log]).lower()
    assert "llm-secret-value" not in combined
    assert "embedding-secret-value" not in combined
    assert "api_key" not in combined
    assert "authorization" not in combined
    assert "bearer " not in combined


def test_runtime_probe_executes_no_network_call(tmp_path, monkeypatch) -> None:
    _clear_relevant_env(monkeypatch)

    def fail_socket(*_args, **_kwargs):
        raise AssertionError("network socket should not be opened")

    monkeypatch.setattr(socket, "socket", fail_socket)
    baseline = probe_runtime_baseline(tmp_path)

    assert baseline["network_calls_executed"] is False


def test_runtime_probe_executes_no_storage_write(tmp_path, monkeypatch) -> None:
    _clear_relevant_env(monkeypatch)
    (tmp_path / ".env").write_text("WORKING_DIR=raw_store\n", encoding="utf-8")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    baseline = probe_runtime_baseline(tmp_path)
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    assert baseline["storage_writes_executed"] is False
    assert before == after
    assert "lightrag.lightrag" not in baseline


def test_working_dir_collision_and_current_state_semantics(tmp_path, monkeypatch) -> None:
    _clear_relevant_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "WORKING_DIR=shared_test_graph_workspace",
                "LIGHTRAG_DSL_INGEST_WORKING_DIR=shared_test_graph_workspace",
                "WORKSPACE=raw_workspace",
                "LIGHTRAG_DSL_INGEST_NAMESPACE=dsl_workspace",
            ]
        ),
        encoding="utf-8",
    )

    baseline = probe_runtime_baseline(tmp_path)
    working_dirs = baseline["working_dirs"]
    report = build_ingestion_baseline_payload(REPO_ROOT)
    conclusions = report["baseline_conclusions"]

    assert working_dirs["raw_and_dsl_share_working_dir"] is True
    assert working_dirs["raw_and_dsl_share_graph_namespace"] is False
    assert working_dirs["runtime_confirmation_required"] is False
    assert conclusions["CURRENT_RAW_AND_DSL_SHARE_WORKING_DIR"]["conclusion"] == "false"
    assert conclusions["CAPABILITY_RAW_AND_DSL_CAN_TARGET_SAME_GRAPH"]["conclusion"] == "true"


def test_fake_embedding_detection_and_mix_risk(tmp_path, monkeypatch) -> None:
    _clear_relevant_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "EMBEDDING_BINDING=fake",
                "EMBEDDING_MODEL=dsl-test-fake-embedding",
                "WORKING_DIR=raw_graph_workspace",
                "LIGHTRAG_DSL_INGEST_WORKING_DIR=dsl_graph_workspace",
            ]
        ),
        encoding="utf-8",
    )

    baseline = probe_runtime_baseline(tmp_path)
    plain = to_plain_dict(baseline)

    assert plain["embedding"]["fake_model_detected"] is True
    assert plain["working_dirs"]["fake_and_real_embedding_mix_detected"] is False
    assert _fake_real_embedding_mix_risk(baseline) in {"MEDIUM", "LOW"}


def test_report_is_serializable_and_contains_all_required_fields() -> None:
    report = build_ingestion_baseline_payload(REPO_ROOT)
    rendered = json.dumps(report, sort_keys=True)
    conclusions = report["baseline_conclusions"]

    assert rendered
    assert REQUIRED_CONCLUSION_FIELDS.issubset(conclusions)
    assert "RAW_AND_DSL_CAN_WRITE_SAME_GRAPH" not in conclusions
    for name in REQUIRED_CONCLUSION_FIELDS:
        conclusion = conclusions[name]
        assert conclusion["conclusion"] in {"true", "false", "unresolved", "HIGH", "MEDIUM", "LOW"}
        assert conclusion["evidence_file"] or conclusion["unresolved_reason"]
        assert conclusion["evidence_line"] or conclusion["unresolved_reason"]
        assert conclusion["evidence_function"] or conclusion["unresolved_reason"]
        assert conclusion["explanation"]


def test_markdown_report_contains_mermaid_architecture() -> None:
    markdown = _render_markdown(build_ingestion_baseline_payload(REPO_ROOT))

    assert "## Architecture Diagram" in markdown
    assert "```mermaid" in markdown
    assert "flowchart TD" in markdown
    assert "run_dsl_knowledge_ingestion" in markdown
    assert "LightRAG.ainsert_custom_kg" in markdown


def test_markdown_report_contains_file_function_line_evidence() -> None:
    markdown = _render_markdown(build_ingestion_baseline_payload(REPO_ROOT))

    assert "## Original Upload Call Chain" in markdown
    assert "## DSL Ingestion Call Chain" in markdown
    assert "lightrag/api/routers/document_routes.py" in markdown
    assert "upload_to_input_dir" in markdown
    assert "lightrag_ext/us_dsl/dsl_knowledge_ingestion_writer.py" in markdown
    assert "_write_batches_in_working_dir" in markdown
    assert "| Step | File | Line | Function |" in markdown


def test_no_lightrag_core_modified() -> None:
    assert (
        _core_diff_check(REPO_ROOT)
        == "No diff in forbidden core/API files for Block 24A-0.1.\n"
    )


def _clear_relevant_env(monkeypatch) -> None:
    for key in list(os.environ):
        if key.startswith(ENV_PREFIXES) or key in ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
