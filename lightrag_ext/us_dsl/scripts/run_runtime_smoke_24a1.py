from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
from dotenv import load_dotenv


ARTIFACT_DIR = Path("artifacts/block_24a1_runtime_smoke")
WORKSPACE_ROOT = ARTIFACT_DIR / "workspaces"
ALLOWED_STORAGE = {
    "kv_storage": "JsonKVStorage",
    "vector_storage": "NanoVectorDBStorage",
    "graph_storage": "NetworkXStorage",
    "doc_status_storage": "JsonDocStatusStorage",
}
FORBIDDEN_CORE_PATHS = [
    "lightrag/lightrag.py",
    "lightrag/operate.py",
    "lightrag/prompt.py",
    "lightrag/api",
]


@dataclass
class SmokeStep:
    name: str
    status: str
    started_at: str
    finished_at: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class SmokeReport:
    block: str
    run_id: str
    repository_path: str
    status: str
    workspace_root: str
    raw_workspace: str
    dsl_workspace: str
    config: dict[str, Any]
    safety: dict[str, Any]
    steps: list[SmokeStep] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    generated_at: str = ""


class SmokeBlocked(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class SmokeIntegrationFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


async def main_async() -> int:
    args = _parse_args()
    repo = _repo_root()
    load_dotenv(repo / ".env", override=False)
    run_id = args.run_id or _new_run_id()
    run_root = (repo / WORKSPACE_ROOT / run_id).resolve()
    raw_workspace = f"block24a1_{run_id}_raw"
    dsl_workspace = f"block24a1_{run_id}_dsl"
    config = _runtime_config()
    report = SmokeReport(
        block="Block 24A-1",
        run_id=run_id,
        repository_path=str(repo),
        status="BLOCKED_BY_ENV",
        workspace_root=str(run_root),
        raw_workspace=raw_workspace,
        dsl_workspace=dsl_workspace,
        config=config,
        safety={
            "writes_only_under": str((repo / WORKSPACE_ROOT).resolve()),
            "uses_local_storage_only": True,
            "calls_upload_route": False,
            "uses_company_documents": False,
            "modifies_core_api": False,
            "dependency_install_attempted": False,
        },
        generated_at=_now(),
    )

    artifact_dir = repo / ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        _prepare_run_workspace(run_root)
        _write_git_status(repo, artifact_dir / "git_status_before.txt")
        _safety_preflight(repo, run_root, raw_workspace, dsl_workspace)
        _dependency_preflight(config)
        report.status = await _run_smoke_workflows(
            args=args,
            repo=repo,
            run_root=run_root,
            raw_workspace=raw_workspace,
            dsl_workspace=dsl_workspace,
            config=config,
            report=report,
        )
    except SmokeBlocked as exc:
        report.status = "BLOCKED_BY_ENV"
        report.steps.append(_failed_step("preflight", exc.code, exc.message, status="blocked"))
    except SmokeIntegrationFailure as exc:
        report.status = "FAIL_INTEGRATION"
        report.steps.append(_failed_step("integration", exc.code, exc.message, status="failed"))
    except Exception as exc:  # Defensive: unexpected wrapper/storage errors are integration failures.
        report.status = _classify_status(exc)
        report.steps.append(
            _failed_step(
                "unexpected_failure",
                _classify_error_code(exc),
                _sanitize(str(exc)),
                status="failed",
            )
        )
    finally:
        report.safety["core_diff_check"] = _core_diff_check(repo)
        _write_report(repo, report)
        _write_git_status(repo, artifact_dir / "git_status_after.txt")
        _append_command_log(repo, args)

    print(f"STATUS={report.status}")
    print(f"REPORT={repo / ARTIFACT_DIR / 'runtime_smoke_report.json'}")
    return 0 if report.status in {"PASS", "BLOCKED_BY_ENV"} else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Block 24A-1 isolated runtime smoke")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--keep-workspace", action="store_true", default=True)
    return parser.parse_args()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _new_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _runtime_config() -> dict[str, Any]:
    embedding_binding = _env("EMBEDDING_BINDING", "ollama")
    llm_binding = _env("LLM_BINDING", "ollama")
    embedding_host = _env("EMBEDDING_BINDING_HOST", _default_host(embedding_binding))
    llm_host = _env("LLM_BINDING_HOST", _default_host(llm_binding))
    embedding_model = _env("EMBEDDING_MODEL", _default_embedding_model(embedding_binding))
    embedding_dim = _env_int("EMBEDDING_DIM", _default_embedding_dim(embedding_binding))
    return {
        "embedding_binding": embedding_binding,
        "embedding_model": embedding_model,
        "embedding_host": _host_only(embedding_host),
        "embedding_dim": embedding_dim,
        "embedding_context_limit": _env_int("EMBEDDING_TOKEN_LIMIT", 8192),
        "embedding_batch_num": _env_int("EMBEDDING_BATCH_NUM", 10),
        "embedding_send_dimensions": _env_bool("EMBEDDING_SEND_DIM", False)
        or embedding_binding in {"jina", "gemini"},
        "embedding_credential_configured": bool(
            _env("EMBEDDING_BINDING_API_KEY", "") or _env("OPENAI_API_KEY", "")
        ),
        "embedding_credential_fingerprint": _fingerprint(
            _env("EMBEDDING_BINDING_API_KEY", "") or _env("OPENAI_API_KEY", "")
        ),
        "llm_binding": llm_binding,
        "llm_model": _env("LLM_MODEL", "mistral-nemo:latest"),
        "llm_host": _host_only(llm_host),
        "llm_timeout": _env_int("LLM_TIMEOUT", 180),
        "llm_max_async": _env_int("MAX_ASYNC", 4),
        "llm_credential_configured": bool(
            _env("LLM_BINDING_API_KEY", "") or _env("OPENAI_API_KEY", "")
        ),
        "llm_credential_fingerprint": _fingerprint(
            _env("LLM_BINDING_API_KEY", "") or _env("OPENAI_API_KEY", "")
        ),
        "proxy_detected": any(
            os.environ.get(key)
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
        ),
        "no_proxy": "configured" if (os.environ.get("NO_PROXY") or os.environ.get("no_proxy")) else "unset",
        **ALLOWED_STORAGE,
    }


def _prepare_run_workspace(run_root: Path) -> None:
    allowed_root = (_repo_root() / WORKSPACE_ROOT).resolve()
    if allowed_root not in run_root.parents:
        raise SmokeBlocked("FAIL_SAFETY_WORKSPACE_ROOT", "Run workspace is outside the allowed artifact root.")
    if run_root.exists():
        raise SmokeBlocked("FAIL_SAFETY_WORKSPACE_EXISTS", "Run workspace already exists; refusing to reuse old workspace.")
    run_root.mkdir(parents=True)


def _safety_preflight(repo: Path, run_root: Path, raw_workspace: str, dsl_workspace: str) -> None:
    if not str(run_root).startswith(str((repo / WORKSPACE_ROOT).resolve())):
        raise SmokeBlocked("FAIL_SAFETY_WORKSPACE_ROOT", "Workspace root is not isolated under artifacts.")
    for workspace in (raw_workspace, dsl_workspace):
        lowered = workspace.lower()
        if any(token in lowered for token in ("prod", "production", "neo4j")):
            raise SmokeBlocked("FAIL_SAFETY_NAMESPACE", f"Unsafe workspace name rejected: {workspace}")
    diff = _core_diff_check(repo)
    if "No diff" not in diff:
        raise SmokeBlocked("FAIL_SAFETY_CORE_DIFF", "Forbidden Core/API paths have local diffs.")


def _dependency_preflight(config: dict[str, Any]) -> None:
    required = {"numpy", "networkx", "nano_vectordb"}
    if config["embedding_binding"] == "openai" or config["llm_binding"] == "openai":
        required.add("openai")
        required.add("tiktoken")
    missing = sorted(name for name in required if importlib.util.find_spec(name) is None)
    if missing:
        raise SmokeBlocked(
            "BLOCKED_MISSING_RUNTIME_DEPENDENCY",
            "Missing runtime dependency for configured binding: " + ", ".join(missing),
        )
    supported = {"openai"}
    unsupported = sorted(
        binding
        for binding in {config["embedding_binding"], config["llm_binding"]}
        if binding not in supported
    )
    if unsupported:
        raise SmokeBlocked(
            "BLOCKED_UNSUPPORTED_BINDING_IN_SMOKE_RUNNER",
            "Smoke runner currently supports configured OpenAI-compatible binding only; unsupported: "
            + ", ".join(unsupported),
        )


async def _run_smoke_workflows(
    *,
    args: argparse.Namespace,
    repo: Path,
    run_root: Path,
    raw_workspace: str,
    dsl_workspace: str,
    config: dict[str, Any],
    report: SmokeReport,
) -> str:
    embedding_func = _build_embedding_func(config)
    llm_func = _build_llm_func(config)

    await _run_step(report, "embedding_wrapper_batch_probe", args.timeout_seconds, _embedding_probe, embedding_func, config)
    await _run_step(report, "query_llm_minimal_probe", args.timeout_seconds, _llm_probe, llm_func)
    await _run_step(
        report,
        "original_raw_ingestion_smoke",
        args.timeout_seconds,
        _raw_ingestion_smoke,
        run_root,
        raw_workspace,
        embedding_func,
        llm_func,
        config,
    )
    await _run_step(
        report,
        "dsl_custom_kg_smoke",
        args.timeout_seconds,
        _dsl_custom_kg_smoke,
        run_root,
        dsl_workspace,
        embedding_func,
        llm_func,
        config,
    )
    await _run_step(
        report,
        "query_smoke_on_dsl_workspace",
        args.timeout_seconds,
        _query_smoke,
        run_root,
        dsl_workspace,
        embedding_func,
        llm_func,
        config,
    )
    return "PASS"


async def _run_step(report: SmokeReport, name: str, timeout_seconds: int, func, *args) -> None:
    step = SmokeStep(name=name, status="running", started_at=_now())
    report.steps.append(step)
    try:
        evidence = await asyncio.wait_for(func(*args), timeout=timeout_seconds)
        step.status = "passed"
        step.evidence = evidence
    except asyncio.TimeoutError as exc:
        step.status = "blocked"
        step.error_code = "BLOCKED_TIMEOUT"
        step.error_message = f"Step exceeded timeout_seconds={timeout_seconds}."
        raise SmokeBlocked(step.error_code, step.error_message) from exc
    except Exception as exc:
        step.status = "failed"
        step.error_code = _classify_error_code(exc)
        step.error_message = _sanitize(str(exc))
        if _is_env_blocker(exc):
            step.status = "blocked"
            raise SmokeBlocked(step.error_code, step.error_message) from exc
        raise SmokeIntegrationFailure(step.error_code, step.error_message) from exc
    finally:
        step.finished_at = _now()


async def _embedding_probe(embedding_func, config: dict[str, Any]) -> dict[str, Any]:
    texts = [
        "Block 24A-1 embedding probe alpha.",
        "Block 24A-1 embedding probe beta.",
        "Block 24A-1 embedding probe gamma.",
    ]
    result = await embedding_func(texts)
    array = np.asarray(result)
    if array.ndim != 2:
        raise SmokeIntegrationFailure("FAIL_EMBEDDING_SHAPE", f"Embedding result ndim={array.ndim}, expected 2.")
    row_count, dim = array.shape
    unique_dims = sorted({len(row) for row in array})
    if row_count != len(texts):
        raise SmokeIntegrationFailure("FAIL_EMBEDDING_COUNT_MISMATCH", f"expected {len(texts)} vectors, got {row_count}.")
    if dim != config["embedding_dim"]:
        raise SmokeIntegrationFailure("FAIL_EMBEDDING_DIMENSION_MISMATCH", f"expected dimension {config['embedding_dim']}, got {dim}.")
    return {
        "input_count": len(texts),
        "vector_count": row_count,
        "dimension": dim,
        "unique_dimensions": unique_dims,
        "configured_dimension": config["embedding_dim"],
        "dtype": str(array.dtype),
        "vector_values_logged": False,
    }


async def _llm_probe(llm_func) -> dict[str, Any]:
    response = await llm_func(
        "Return a short confirmation sentence containing the phrase LIGHTRAG_SMOKE_OK.",
        system_prompt="You are executing a minimal runtime smoke test. Keep the response short.",
        history_messages=[],
    )
    text = str(response or "")
    if not text.strip():
        raise SmokeIntegrationFailure("FAIL_LLM_EMPTY_RESPONSE", "LLM wrapper returned an empty response.")
    return {"response_chars": len(text), "contains_marker": "LIGHTRAG_SMOKE_OK" in text, "response_excerpt": text[:160]}


async def _raw_ingestion_smoke(run_root: Path, workspace: str, embedding_func, llm_func, config: dict[str, Any]) -> dict[str, Any]:
    rag = _make_rag(run_root, workspace, embedding_func, llm_func, config)
    try:
        await rag.initialize_storages()
        track_id = await rag.ainsert(
            _raw_smoke_text(),
            ids="block24a1-raw-doc",
            file_paths="block24a1_raw_synthetic.txt",
            track_id="block24a1-raw-track",
        )
        await rag.finalize_storages()
    finally:
        try:
            await rag.finalize_storages()
        except Exception:
            pass
    counts = _workspace_counts(run_root, workspace)
    if counts["text_chunks"] < 1 or counts["chunks_vdb"] < 1:
        raise SmokeIntegrationFailure("FAIL_RAW_CHUNK_STORAGE", f"raw chunk counts invalid: {counts}")
    if counts["graph_nodes"] < 1 or counts["entities_vdb"] < 1:
        raise SmokeIntegrationFailure("FAIL_RAW_ENTITY_GRAPH_STORAGE", f"raw graph/entity counts invalid: {counts}")
    if counts["doc_status_processed"] < 1:
        raise SmokeIntegrationFailure("FAIL_RAW_DOC_STATUS", f"raw doc status not processed: {counts}")
    return {"track_id": track_id, "counts": counts}


async def _dsl_custom_kg_smoke(run_root: Path, workspace: str, embedding_func, llm_func, config: dict[str, Any]) -> dict[str, Any]:
    rag = _make_rag(run_root, workspace, embedding_func, llm_func, config)
    custom_kg = _custom_kg_payload()
    try:
        await rag.initialize_storages()
        await rag.ainsert_custom_kg(custom_kg, full_doc_id="block24a1-custom-kg-doc")
        await rag.finalize_storages()
    finally:
        try:
            await rag.finalize_storages()
        except Exception:
            pass
    counts = _workspace_counts(run_root, workspace)
    expected = {
        "text_chunks": 1,
        "chunks_vdb": 1,
        "graph_nodes": 2,
        "graph_edges": 1,
        "entities_vdb": 2,
        "relationships_vdb": 1,
    }
    mismatches = {key: {"expected": val, "actual": counts.get(key)} for key, val in expected.items() if counts.get(key) != val}
    if mismatches:
        raise SmokeIntegrationFailure("FAIL_DSL_CUSTOM_KG_COUNTS", json.dumps(mismatches, sort_keys=True))
    return {"input_counts": {"chunks": 1, "entities": 2, "relationships": 1}, "storage_counts": counts}


async def _query_smoke(run_root: Path, workspace: str, embedding_func, llm_func, config: dict[str, Any]) -> dict[str, Any]:
    from lightrag.base import QueryParam

    rag = _make_rag(run_root, workspace, embedding_func, llm_func, config)
    try:
        await rag.initialize_storages()
        answer = await rag.aquery(
            "In the block 24A-1 test graph, what determines Bank Status?",
            QueryParam(mode="hybrid", top_k=5, chunk_top_k=5, enable_rerank=False),
        )
        await rag.finalize_storages()
    finally:
        try:
            await rag.finalize_storages()
        except Exception:
            pass
    text = str(answer or "")
    lowered = text.lower()
    hit = any(marker in lowered for marker in ("bank status", "query condition", "查询条件"))
    if not hit:
        raise SmokeIntegrationFailure("FAIL_QUERY_ANSWER_MISSING_EXPECTED_SEMANTICS", text[:240])
    return {"answer_chars": len(text), "contains_expected_semantics": hit, "answer_excerpt": text[:240]}


def _make_rag(run_root: Path, workspace: str, embedding_func, llm_func, config: dict[str, Any]):
    from lightrag import LightRAG

    return LightRAG(
        working_dir=str(run_root),
        workspace=workspace,
        llm_model_func=llm_func,
        llm_model_name=config["llm_model"],
        llm_model_max_async=1,
        summary_max_tokens=512,
        chunk_token_size=512,
        chunk_overlap_token_size=32,
        embedding_func=embedding_func,
        default_llm_timeout=config["llm_timeout"],
        default_embedding_timeout=60,
        kv_storage=ALLOWED_STORAGE["kv_storage"],
        vector_storage=ALLOWED_STORAGE["vector_storage"],
        graph_storage=ALLOWED_STORAGE["graph_storage"],
        doc_status_storage=ALLOWED_STORAGE["doc_status_storage"],
        vector_db_storage_cls_kwargs={"cosine_better_than_threshold": 0.2},
        enable_llm_cache=False,
        enable_llm_cache_for_entity_extract=False,
        max_parallel_insert=1,
        addon_params={"language": "English"},
    )


def _build_embedding_func(config: dict[str, Any]):
    from lightrag.llm.openai import openai_embed
    from lightrag.utils import EmbeddingFunc

    actual_func = openai_embed.func if hasattr(openai_embed, "func") else openai_embed
    credential = _env("EMBEDDING_BINDING_API_KEY", "") or _env("OPENAI_API_KEY", "")

    async def embedding_wrapper(texts, embedding_dim=None, context="document"):
        kwargs = {
            "texts": texts,
            "model": config["embedding_model"],
            "base_url": _env("EMBEDDING_BINDING_HOST", None),
            "api_key": credential,
            "context": context,
        }
        if config["embedding_send_dimensions"]:
            kwargs["embedding_dim"] = embedding_dim
        return await actual_func(**kwargs)

    return EmbeddingFunc(
        embedding_dim=config["embedding_dim"],
        max_token_size=config["embedding_context_limit"],
        func=embedding_wrapper,
        send_dimensions=config["embedding_send_dimensions"],
        model_name=config["embedding_model"],
        supports_asymmetric=True,
    )


def _build_llm_func(config: dict[str, Any]):
    from lightrag.llm.openai import openai_complete_if_cache

    credential = _env("LLM_BINDING_API_KEY", "") or _env("OPENAI_API_KEY", "")

    async def llm_wrapper(prompt, system_prompt=None, history_messages=None, keyword_extraction=False, **kwargs):
        return await openai_complete_if_cache(
            config["llm_model"],
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages or [],
            base_url=_env("LLM_BINDING_HOST", None),
            api_key=credential,
            timeout=config["llm_timeout"],
            keyword_extraction=keyword_extraction,
            **kwargs,
        )

    return llm_wrapper


def _raw_smoke_text() -> str:
    return (
        "Block 24A-1 synthetic runtime smoke document. "
        "Bank Status is a test entity used only for runtime validation. "
        "Query Condition is another test entity. "
        "Bank Status is determined by Query Condition when the account is active, KYC is complete, and no sanctions flag is present. "
        "This text contains no company design document or real business user story."
    )


def _custom_kg_payload() -> dict[str, Any]:
    return {
        "chunks": [
            {
                "content": "Bank Status is determined by Query Condition in the Block 24A-1 custom KG smoke graph.",
                "source_id": "block24a1-chunk-1",
                "file_path": "block24a1_custom_kg_synthetic.txt",
                "chunk_order_index": 0,
            }
        ],
        "entities": [
            {
                "entity_name": "Bank Status",
                "entity_type": "TEST_ENTITY",
                "description": "Synthetic entity representing a bank status result for smoke testing.",
                "source_id": "block24a1-chunk-1",
                "file_path": "block24a1_custom_kg_synthetic.txt",
            },
            {
                "entity_name": "Query Condition",
                "entity_type": "TEST_ENTITY",
                "description": "Synthetic entity representing the query condition used to determine Bank Status.",
                "source_id": "block24a1-chunk-1",
                "file_path": "block24a1_custom_kg_synthetic.txt",
            },
        ],
        "relationships": [
            {
                "src_id": "Bank Status",
                "tgt_id": "Query Condition",
                "description": "Bank Status is determined by Query Condition in this synthetic smoke graph.",
                "keywords": "determined_by,block24a1_smoke",
                "weight": 1.0,
                "source_id": "block24a1-chunk-1",
                "file_path": "block24a1_custom_kg_synthetic.txt",
            }
        ],
    }


def _workspace_counts(run_root: Path, workspace: str) -> dict[str, Any]:
    workspace_dir = run_root / workspace
    graph_nodes = 0
    graph_edges = 0
    graph_files = sorted(workspace_dir.glob("graph_*.graphml"))
    if graph_files:
        import networkx as nx

        graph = nx.read_graphml(graph_files[0])
        graph_nodes = graph.number_of_nodes()
        graph_edges = graph.number_of_edges()
    return {
        "text_chunks": _kv_count(workspace_dir / "kv_store_text_chunks.json"),
        "full_docs": _kv_count(workspace_dir / "kv_store_full_docs.json"),
        "doc_status": _kv_count(workspace_dir / "kv_store_doc_status.json"),
        "doc_status_processed": _doc_status_processed_count(workspace_dir / "kv_store_doc_status.json"),
        "chunks_vdb": _vdb_count(workspace_dir / "vdb_chunks.json"),
        "entities_vdb": _vdb_count(workspace_dir / "vdb_entities.json"),
        "relationships_vdb": _vdb_count(workspace_dir / "vdb_relationships.json"),
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "workspace_dir": str(workspace_dir),
    }


def _kv_count(path: Path) -> int:
    data = _read_json(path)
    return len(data) if isinstance(data, dict) else 0


def _doc_status_processed_count(path: Path) -> int:
    data = _read_json(path)
    if not isinstance(data, dict):
        return 0
    return sum(1 for item in data.values() if isinstance(item, dict) and item.get("status") == "PROCESSED")


def _vdb_count(path: Path) -> int:
    data = _read_json(path)
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return len(data["data"])
    if isinstance(data, dict) and isinstance(data.get("storage"), dict):
        return len(data["storage"])
    return 0


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_report(repo: Path, report: SmokeReport) -> None:
    artifact_dir = repo / ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    (artifact_dir / "runtime_smoke_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "runtime_smoke_report.md").write_text(_render_markdown(payload), encoding="utf-8")
    (artifact_dir / "core_diff_check.txt").write_text(report.safety.get("core_diff_check", ""), encoding="utf-8")


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Block 24A-1 Runtime Smoke Report",
        "",
        f"- Final status: `{payload['status']}`",
        f"- Run ID: `{payload['run_id']}`",
        f"- Workspace root: `{payload['workspace_root']}`",
        "",
        "## Runtime Config",
        "",
        f"- Embedding: `{payload['config']['embedding_binding']}` / `{payload['config']['embedding_model']}` / dim `{payload['config']['embedding_dim']}` / host `{payload['config']['embedding_host']}`",
        f"- Embedding sends dimensions: `{payload['config']['embedding_send_dimensions']}`",
        f"- LLM: `{payload['config']['llm_binding']}` / `{payload['config']['llm_model']}` / host `{payload['config']['llm_host']}`",
        f"- Local storage: `{payload['config']['kv_storage']}`, `{payload['config']['vector_storage']}`, `{payload['config']['graph_storage']}`, `{payload['config']['doc_status_storage']}`",
        "",
        "## Safety Boundary",
        "",
        *[f"- {key}: `{value}`" for key, value in payload["safety"].items()],
        "",
        "## Steps",
        "",
        "| Step | Status | Error Code | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for step in payload["steps"]:
        evidence = json.dumps(step.get("evidence") or {}, sort_keys=True)
        lines.append(
            f"| {step['name']} | `{step['status']}` | `{step.get('error_code')}` | `{_escape_table(evidence[:500])}` |"
        )
        if step.get("error_message"):
            lines.append(f"| {step['name']} detail | | | `{_escape_table(step['error_message'])}` |")
    lines.extend(["", "## Status Rules", "", "- PASS requires all real model probes and both isolated storage smokes to pass.", "- BLOCKED_BY_ENV means runtime environment prevented proof without identifying a LightRAG integration bug.", "- FAIL_INTEGRATION means the gateway responded or local storage ran but wrapper/storage semantics failed.", "- FAIL_SAFETY means the run touched a forbidden boundary.", ""])
    return "\n".join(lines)


def _append_command_log(repo: Path, args: argparse.Namespace) -> None:
    log_path = repo / ARTIFACT_DIR / "command_log.txt"
    with log_path.open("a", encoding="utf-8") as file:
        file.write("\nBlock 24A-1 command executed:\n")
        file.write(
            ".venv/bin/python -m lightrag_ext.us_dsl.scripts.run_runtime_smoke_24a1 "
            f"--timeout-seconds {args.timeout_seconds}\n"
        )


def _write_git_status(repo: Path, path: Path) -> None:
    import subprocess

    result = subprocess.run(["git", "status", "--short", "--branch"], cwd=repo, check=False, capture_output=True, text=True)
    path.write_text(result.stdout, encoding="utf-8")


def _core_diff_check(repo: Path) -> str:
    import subprocess

    result = subprocess.run(["git", "diff", "--", *FORBIDDEN_CORE_PATHS], cwd=repo, check=False, capture_output=True, text=True)
    if result.stdout.strip():
        return result.stdout
    return "No diff in forbidden core/API files for Block 24A-1.\n"


def _failed_step(name: str, code: str, message: str, *, status: str) -> SmokeStep:
    now = _now()
    return SmokeStep(name=name, status=status, started_at=now, finished_at=now, error_code=code, error_message=_sanitize(message))


def _classify_status(exc: Exception) -> str:
    if _is_safety_error(exc):
        return "FAIL_SAFETY"
    if _is_env_blocker(exc):
        return "BLOCKED_BY_ENV"
    return "FAIL_INTEGRATION"


def _classify_error_code(exc: Exception) -> str:
    text = str(exc).lower()
    if any(code in text for code in ("401", "403", "unauthorized", "forbidden")):
        return "BLOCKED_MODEL_AUTH"
    if any(code in text for code in ("timeout", "timed out")):
        return "BLOCKED_TIMEOUT"
    if any(code in text for code in ("connection", "dns", "name resolution", "network")):
        return "BLOCKED_NETWORK"
    if any(code in text for code in ("dimension", "vector count", "cannot be evenly divided", "reshape")):
        return "FAIL_VECTOR_DIMENSION_OR_COUNT"
    return "FAIL_RUNTIME_SMOKE"


def _is_env_blocker(exc: Exception) -> bool:
    if isinstance(exc, SmokeBlocked):
        return True
    return _classify_error_code(exc).startswith("BLOCKED")


def _is_safety_error(exc: Exception) -> bool:
    return isinstance(exc, SmokeBlocked) and exc.code.startswith("FAIL_SAFETY")


def _sanitize(text: str) -> str:
    sanitized = text
    for value in (
        _env("LLM_BINDING_API_KEY", ""),
        _env("EMBEDDING_BINDING_API_KEY", ""),
        _env("OPENAI_API_KEY", ""),
    ):
        if value:
            sanitized = sanitized.replace(value, "<redacted>")
    sanitized = sanitized.replace("Authorization", "credential-header")
    return sanitized[:1000]


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _env(key: str, default: str | None = None) -> str | None:
    value = os.getenv(key)
    return value if value not in {None, ""} else default


def _env_int(key: str, default: int | None) -> int | None:
    value = _env(key, None)
    if value is None:
        return default
    return int(value)


def _env_bool(key: str, default: bool) -> bool:
    value = _env(key, None)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y"}


def _default_host(binding: str) -> str:
    return {
        "openai": "https://api.openai.com/v1",
        "azure_openai": "https://api.openai.com/v1",
        "ollama": "http://localhost:11434",
        "gemini": "https://generativelanguage.googleapis.com",
    }.get(binding, "http://localhost:11434")


def _default_embedding_model(binding: str) -> str | None:
    return {"openai": "text-embedding-3-small", "azure_openai": "text-embedding-3-large"}.get(binding)


def _default_embedding_dim(binding: str) -> int | None:
    return {"openai": 1536, "azure_openai": 1536, "jina": 2048, "gemini": 1536}.get(binding)


def _host_only(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"//{value}")
    return parsed.hostname or parsed.netloc or value


def _fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
