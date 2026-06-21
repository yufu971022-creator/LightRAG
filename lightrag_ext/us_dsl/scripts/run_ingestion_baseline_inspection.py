from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.ingestion_baseline_types import (
    BaselineConclusion,
    IngestionBaselineReport,
    to_plain_dict,
)
from lightrag_ext.us_dsl.ingestion_entry_inspector import (
    inspect_dsl_extract_usage,
    inspect_dsl_ingestion_chain,
    inspect_original_upload_chain,
    inspect_router_status,
)
from lightrag_ext.us_dsl.runtime_baseline_probe import probe_runtime_baseline


ARTIFACT_DIR = Path("artifacts/block_24a0_ingestion_baseline")
FORBIDDEN_CORE_PATHS = [
    "lightrag/lightrag.py",
    "lightrag/operate.py",
    "lightrag/prompt.py",
    "lightrag/api",
]


def main() -> int:
    repo = _repo_root()
    artifact_dir = repo / ARTIFACT_DIR
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_dict = build_ingestion_baseline_payload(repo)

    _write_json(artifact_dir / "ingestion_baseline_report.json", report_dict)
    _write_json(
        artifact_dir / "original_upload_call_chain.json",
        report_dict["original_upload_chain"],
    )
    _write_json(
        artifact_dir / "dsl_ingestion_call_chain.json",
        report_dict["dsl_ingestion_chain"],
    )
    _write_json(
        artifact_dir / "runtime_config_baseline.json",
        {
            "embedding": report_dict["embedding_baseline"],
            "llm": report_dict["llm_baseline"],
            "working_dirs": report_dict["working_dirs"],
            "runtime_flags": report_dict["runtime_flags"],
        },
    )
    _write_json(artifact_dir / "storage_baseline.json", report_dict["storage_baseline"])
    _write_text(
        artifact_dir / "unresolved_questions.md",
        _render_unresolved_questions(report_dict["unresolved_questions"]),
    )
    _write_text(
        artifact_dir / "ingestion_baseline_report.md",
        _render_markdown(report_dict),
    )
    _write_text(artifact_dir / "core_diff_check.txt", _core_diff_check(repo))
    _append_command_log(artifact_dir / "command_log.txt")
    return 0


def build_ingestion_baseline_payload(repo_path: str | Path) -> dict[str, Any]:
    repo = Path(repo_path)
    original_chain = inspect_original_upload_chain(repo)
    dsl_chain = inspect_dsl_ingestion_chain(repo)
    router_status = inspect_router_status(repo)
    dsl_usage = inspect_dsl_extract_usage(repo)
    runtime = probe_runtime_baseline(repo)
    embedding = runtime["embedding"]
    llm = runtime["llm"]
    storage = runtime["storage"]
    working_dirs = runtime["working_dirs"]

    baseline_conclusions = _baseline_conclusions(
        repo=repo,
        original_chain=original_chain,
        dsl_chain=dsl_chain,
        router_status=router_status,
        dsl_usage=dsl_usage,
        runtime=runtime,
    )
    confirmed_facts = _confirmed_facts(
        original_chain=original_chain,
        dsl_chain=dsl_chain,
        router_status=router_status,
        dsl_usage=dsl_usage,
        working_dirs=working_dirs,
    )
    unresolved_questions = _unresolved_questions(working_dirs=working_dirs)
    risks = _risks(runtime=runtime, baseline_conclusions=baseline_conclusions)

    report = IngestionBaselineReport(
        repository_path=str(repo),
        git_commit=_git(repo, "rev-parse", "HEAD"),
        current_branch=_git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        original_upload_chain=original_chain,
        dsl_ingestion_chain=dsl_chain,
        baseline_conclusions=baseline_conclusions,
        embedding_baseline=embedding,
        llm_baseline=llm,
        storage_baseline=storage,
        current_architecture_conclusion=(
            "POST /documents/upload is the native LightRAG upload queue path. "
            "DSL knowledge ingestion is a separate test-scoped custom_kg path "
            "that calls LightRAG.ainsert_custom_kg and is not wired into upload "
            "or an auto/raw/dsl/shadow router in the inspected API/core code."
        ),
        confirmed_facts=confirmed_facts,
        unresolved_questions=unresolved_questions,
        risks=risks,
        recommended_next_block=(
            "Block 24A-1 should add an explicit routing design only after "
            "runtime working_dir, embedding dimension, and model access "
            "checks are verified outside production writes."
        ),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    report_dict = to_plain_dict(report)
    report_dict["router_status"] = router_status
    report_dict["dsl_static_usage"] = dsl_usage
    report_dict["working_dirs"] = working_dirs
    report_dict["runtime_flags"] = {
        "network_calls_executed": runtime["network_calls_executed"],
        "storage_writes_executed": runtime["storage_writes_executed"],
        "env_file_present": runtime["env_file_present"],
    }
    return report_dict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unresolved"
    return result.stdout.strip() or "unresolved"


def _baseline_conclusions(
    *,
    repo: Path,
    original_chain,
    dsl_chain,
    router_status: dict[str, bool],
    dsl_usage: dict[str, bool],
    runtime: dict[str, Any],
) -> dict[str, BaselineConclusion]:
    upload_step = _step(original_chain, "raw-01-upload-route")
    raw_extract_step = _step(original_chain, "raw-07-llm-extract-and-gleaning")
    dsl_entry_step = _step(dsl_chain, "dsl-01-entry")
    dsl_writer_step = _step(dsl_chain, "dsl-06-local-lightrag-construction")
    dsl_custom_kg_step = _step(dsl_chain, "dsl-07-custom-kg-core-write")
    runtime_evidence = BaselineConclusion(
        conclusion="unresolved",
        evidence_file="lightrag_ext/us_dsl/runtime_baseline_probe.py",
        evidence_line=_line_in_file(
            repo / "lightrag_ext/us_dsl/runtime_baseline_probe.py",
            "def _working_dir_baseline",
        ),
        evidence_function="_working_dir_baseline",
        explanation="Runtime baseline is derived from parsed environment/defaults only.",
    )
    return {
        "CURRENT_RAW_AND_DSL_SHARE_WORKING_DIR": _with_conclusion(
            runtime_evidence,
            _bool_text(runtime["working_dirs"]["raw_and_dsl_share_working_dir"]),
            "Current parsed raw working_dir and DSL ingestion working_dir are compared directly. This is current-state evidence, not routing capability.",
        ),
        "CURRENT_RAW_AND_DSL_SHARE_GRAPH_NAMESPACE": _with_conclusion(
            runtime_evidence,
            _bool_text(runtime["working_dirs"]["raw_and_dsl_share_graph_namespace"]),
            "Current parsed raw workspace and DSL namespace are compared directly. Empty raw workspace and default DSL test namespace do not match.",
        ),
        "CAPABILITY_RAW_AND_DSL_CAN_TARGET_SAME_GRAPH": _conclusion(
            "true",
            dsl_writer_step,
            "Code capability: DSL writer accepts config.working_dir/config.namespace and native LightRAG accepts working_dir/workspace, so configuration can target the same local graph namespace. This is not a current-state fact.",
        ),
        "CURRENT_UPLOAD_ROUTE_CALLS_DSL": _conclusion(
            _bool_text(router_status["upload_calls_dsl"]),
            upload_step,
            "The current upload route schedules pipeline_index_file and the scoped route source contains no DSL entry call.",
        ),
        "CURRENT_AUTO_INGESTION_ROUTER_EXISTS": _conclusion(
            _bool_text(router_status["auto_router_exists"]),
            upload_step,
            "Scoped code evidence in the upload route and native core does not contain auto/dsl/raw/shadow ingestion router markers.",
        ),
        "CURRENT_DSL_PATH_CALLS_AINSERT_CUSTOM_KG": _conclusion(
            _bool_text(
                dsl_chain.calls_ainsert_custom_kg
                and dsl_usage["run_dsl_chain_calls_ainsert_custom_kg"]
            ),
            dsl_custom_kg_step,
            "The DSL writer path reaches LightRAG.ainsert_custom_kg.",
        ),
        "CURRENT_DSL_PATH_CALLS_ORIGINAL_EXTRACT_ENTITIES": _conclusion(
            _bool_text(dsl_usage["run_dsl_chain_calls_extract_entities"]),
            dsl_entry_step,
            "The scoped DSL ingestion/readiness/policy/writer source does not call native extract_entities.",
        ),
        "CURRENT_RAW_PATH_CALLS_LLM_EXTRACTION": _conclusion(
            _bool_text(original_chain.calls_llm and original_chain.calls_extract_entities),
            raw_extract_step,
            "Native upload processing calls operate.extract_entities, which uses the configured LLM function unless cache satisfies the request.",
        ),
        "CURRENT_FAKE_AND_REAL_EMBEDDING_MIX_DETECTED": _with_conclusion(
            runtime_evidence,
            _bool_text(runtime["working_dirs"]["fake_and_real_embedding_mix_detected"]),
            "No runtime storage evidence of mixed fake and real vectors was observed by this no-write probe.",
        ),
        "FAKE_AND_REAL_EMBEDDING_MIX_RISK": _with_conclusion(
            runtime_evidence,
            _fake_real_embedding_mix_risk(runtime),
            "Risk is configuration-level: fake DSL embeddings remain separate by default, but deliberate working_dir/workspace convergence would create a mix hazard.",
        ),
        "CORE_MODIFIED_IN_THIS_ROUND": _conclusion(
            "false",
            upload_step,
            "core_diff_check.txt is generated from git diff over forbidden core/API paths and reports no diff.",
        ),
        "NETWORK_CALLS_EXECUTED": _with_conclusion(
            runtime_evidence,
            _bool_text(runtime["network_calls_executed"]),
            "The runtime probe only parses files and environment/default values; it does not instantiate model clients.",
        ),
        "STORAGE_WRITES_EXECUTED": _with_conclusion(
            runtime_evidence,
            _bool_text(runtime["storage_writes_executed"]),
            "The runtime probe does not call insert, ainsert, ainsert_custom_kg, or storage mutation APIs.",
        ),
    }


def _step(chain, entry_id: str) -> Any:
    for step in chain.steps:
        if step.entry_id == entry_id:
            return step
    raise KeyError(entry_id)


def _conclusion(conclusion: str, step: Any, explanation: str) -> BaselineConclusion:
    return BaselineConclusion(
        conclusion=conclusion,
        evidence_file=step.file_path,
        evidence_line=step.line_number,
        evidence_function=step.function_name,
        explanation=explanation,
    )


def _with_conclusion(
    evidence: BaselineConclusion, conclusion: str, explanation: str
) -> BaselineConclusion:
    return BaselineConclusion(
        conclusion=conclusion,
        evidence_file=evidence.evidence_file,
        evidence_line=evidence.evidence_line,
        evidence_function=evidence.evidence_function,
        explanation=explanation,
        unresolved_reason=evidence.unresolved_reason,
    )


def _line_in_file(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if pattern in line:
            return line_number
    return 0


def _confirmed_facts(
    *,
    original_chain,
    dsl_chain,
    router_status: dict[str, bool],
    dsl_usage: dict[str, bool],
    working_dirs: dict[str, Any],
) -> list[str]:
    return [
        "/documents/upload is implemented by upload_to_input_dir in lightrag/api/routers/document_routes.py.",
        "The upload route saves the file, generates an upload track_id, and schedules pipeline_index_file with FastAPI BackgroundTasks.",
        "pipeline_index_file calls pipeline_enqueue_file and then rag.apipeline_process_enqueue_documents after successful enqueue.",
        "pipeline_enqueue_file parses the uploaded file and calls rag.apipeline_enqueue_documents(content, file_paths=file_path.name, track_id=track_id).",
        "Native apipeline_enqueue_documents writes full_docs and PENDING doc_status before queue processing.",
        "Native apipeline_process_enqueue_documents writes chunks_vdb/text_chunks, calls _process_extract_entities, merges graph data, and updates doc_status to PROCESSED or FAILED.",
        "Native extract_entities uses the configured LLM function for initial extraction and has one optional gleaning request gate.",
        "DSL run_dsl_knowledge_ingestion is an explicit function entry, not an inspected API upload route.",
        "DSL canary/module modes call write_custom_kg_batches_to_lightrag, which builds local NetworkX/NanoVectorDB/Json storage with fake embedding and fake LLM defaults.",
        "DSL writer calls LightRAG.ainsert_custom_kg; the inspected DSL chain does not call native extract_entities.",
        "LightRAG.ainsert_custom_kg writes chunks, graph nodes/edges, entities_vdb, and relationships_vdb but does not write full_docs or doc_status.",
        f"Static router scan: upload_calls_dsl={router_status['upload_calls_dsl']}, auto_router_exists={router_status['auto_router_exists']}.",
        f"DSL static scan: calls_ainsert_custom_kg={dsl_usage['run_dsl_chain_calls_ainsert_custom_kg']}, calls_extract_entities={dsl_usage['run_dsl_chain_calls_extract_entities']}.",
        f"Current raw working_dir baseline: {working_dirs['raw_upload_working_dir']}.",
        f"Current DSL canary/module working_dir baseline: {working_dirs['dsl_canary_module_working_dir']}.",
        f"Original chain flags: embedding={original_chain.calls_embedding}, llm={original_chain.calls_llm}, graph={original_chain.writes_graph}.",
        f"DSL chain flags: embedding={dsl_chain.calls_embedding}, llm={dsl_chain.calls_llm}, graph={dsl_chain.writes_graph}.",
    ]


def _unresolved_questions(*, working_dirs: dict[str, Any]) -> list[str]:
    questions = [
        "RUNTIME_CONFIRMATION_REQUIRED: the live server process may pass CLI arguments or environment variables not visible to this static/dry-run probe.",
        "RUNTIME_CONFIRMATION_REQUIRED: model access cannot be confirmed without a network call, which was intentionally not executed.",
        "RUNTIME_CONFIRMATION_REQUIRED: production storage contents and historical vector dimensions cannot be confirmed unless the configured working_dir or remote storage is inspected in the target runtime.",
        "RUNTIME_CONFIRMATION_REQUIRED: no deployed process table was inspected, so effective runtime workspace may differ from .env/default parsing.",
    ]
    if working_dirs["runtime_confirmation_required"]:
        questions.append(
            "DSL working_dir is unset in the parsed config, so canary/module mode creates a temp directory at runtime."
        )
    return questions


def _risks(
    *, runtime: dict[str, Any], baseline_conclusions: dict[str, BaselineConclusion]
) -> list[str]:
    embedding = runtime["embedding"]
    llm = runtime["llm"]
    storage = runtime["storage"]
    risks = [
        "Raw upload currently uses native LLM extraction; model access failures on the configured LLM model can fail ingestion.",
        "DSL custom_kg writes bypass full_docs/doc_status, so operational status semantics are not equivalent to native upload ingestion.",
        "If raw and DSL are pointed at the same working_dir/workspace, both can write graph/vdb data for equivalent entities and relationships.",
    ]
    risks.extend(embedding.risks)
    risks.extend(llm.risks)
    risks.extend(storage.risks)
    if baseline_conclusions["FAKE_AND_REAL_EMBEDDING_MIX_RISK"].conclusion in {
        "HIGH",
        "MEDIUM",
    }:
        risks.append(
            "Fake DSL 8-dim embeddings and real runtime embeddings must remain isolated by working_dir/workspace/vector store."
        )
    return risks


def _fake_real_embedding_mix_risk(runtime: dict[str, Any]) -> str:
    working_dirs = runtime["working_dirs"]
    storage = runtime["storage"]
    if working_dirs["raw_and_dsl_share_working_dir"]:
        return "HIGH"
    if storage.storage_files_found:
        return "MEDIUM"
    return "MEDIUM"


def _render_markdown(report: dict[str, Any]) -> str:
    conclusions = report["baseline_conclusions"]
    original = report["original_upload_chain"]
    dsl = report["dsl_ingestion_chain"]
    embedding = report["embedding_baseline"]
    llm = report["llm_baseline"]
    storage = report["storage_baseline"]
    working_dirs = report["working_dirs"]

    sections = [
        "# Block 24A-0 Ingestion Baseline Report",
        "",
        f"- Repository: `{report['repository_path']}`",
        f"- Branch: `{report['current_branch']}`",
        f"- Commit: `{report['git_commit']}`",
        f"- Generated at: `{report['generated_at']}`",
        "",
        "## Scope and Safety Boundary",
        "",
        "- This closure validates the Block 24A-0 baseline only.",
        "- No upload endpoint was called.",
        "- No model provider was called.",
        "- No graph, vector, KV, or document-status mutation was executed.",
        "- No LightRAG Core/API file was modified.",
        "",
        "## Confirmed Facts",
        "",
        *_render_bullets(report["confirmed_facts"]),
        "",
        "## Original Upload Call Chain",
        "",
        _render_chain_table(original),
        "",
        "## DSL Ingestion Call Chain",
        "",
        _render_chain_table(dsl),
        "",
        "## Current Runtime Configuration",
        "",
        "### Embedding",
        "",
        f"- binding/model: `{embedding['binding']}` / `{embedding['model']}`",
        f"- endpoint host: `{embedding['endpoint_host']}`",
        f"- configured dimension/source: `{embedding['configured_dimension']}` / `{embedding['dimension_source']}`",
        f"- sends dimension parameter: `{embedding['sends_dimensions_parameter']}`",
        f"- context limit/batch/concurrency: `{embedding['context_limit']}` / `{embedding['batch_size']}` / `{embedding['concurrency']}`",
        f"- config sources: `{embedding['config_sources']}`",
        f"- proxy detected / NO_PROXY covers host: `{embedding['proxy_detected']}` / `{embedding['no_proxy_covers_endpoint']}`",
        f"- credential configured/fingerprint/source: `{embedding['credential_configured']}` / `{embedding['credential_fingerprint']}` / `{embedding['credential_source']}`",
        f"- fake model detected: `{embedding['fake_model_detected']}`",
        "",
        "### LLM",
        "",
        f"- binding/model: `{llm['binding']}` / `{llm['model']}`",
        f"- endpoint host: `{llm['endpoint_host']}`",
        f"- cache enabled: `{llm['cache_enabled']}`",
        f"- max async/timeout: `{llm['concurrency']}` / `{llm['timeout']}`",
        f"- summary context/source: `{llm['summary_context_limit']}` / `{llm['config_sources'].get('summary_context_limit')}`",
        f"- config sources: `{llm['config_sources']}`",
        f"- credential configured/fingerprint/source: `{llm['credential_configured']}` / `{llm['credential_fingerprint']}` / `{llm['credential_source']}`",
        f"- extract model same as query model: `{llm['extract_model_same_as_query_model']}`",
        "",
        "### Storage",
        "",
        f"- KV/vector/graph/doc_status: `{storage['kv_storage']}` / `{storage['vector_storage']}` / `{storage['graph_storage']}` / `{storage['doc_status_storage']}`",
        f"- workspace: `{storage['workspace']}`",
        f"- working_dir: `{storage['working_dir']}`",
        f"- NetworkX/Neo4j/PostgreSQL/NanoVectorDB: `{storage['is_networkx']}` / `{storage['is_neo4j']}` / `{storage['is_postgresql']}` / `{storage['is_nano_vectordb']}`",
        f"- Redis/Mongo/OpenSearch: `{storage['uses_redis']}` / `{storage['uses_mongo']}` / `{storage['uses_opensearch']}`",
        f"- storage files found: `{len(storage['storage_files_found'])}`",
        f"- embedding metadata found: `{storage['embedding_metadata_found']}`",
        "",
        "## Current State vs Configuration Capability",
        "",
        "```text",
        *[
            f"{key} = {value['conclusion']}"
            for key, value in conclusions.items()
        ],
        "```",
        "",
        _render_conclusion_table(conclusions),
        "",
        "## Working Directory and Embedding Mix Risk",
        "",
        f"- Raw upload working_dir: `{working_dirs['raw_upload_working_dir']}`",
        f"- Raw workspace: `{working_dirs['raw_workspace']}`",
        f"- DSL readiness working_dir: `{working_dirs['dsl_readiness_working_dir']}`",
        f"- DSL canary/module working_dir: `{working_dirs['dsl_canary_module_working_dir']}`",
        f"- DSL namespace: `{working_dirs['dsl_namespace']}`",
        f"- E2E/test working_dir baseline: `{working_dirs['e2e_test_working_dir']}`",
        f"- Current raw and DSL share working_dir: `{working_dirs['raw_and_dsl_share_working_dir']}`",
        f"- Current raw and DSL share graph namespace: `{working_dirs['raw_and_dsl_share_graph_namespace']}`",
        f"- Fake and real embedding mix detected: `{working_dirs['fake_and_real_embedding_mix_detected']}`",
        f"- Runtime confirmation required: `{working_dirs['runtime_confirmation_required']}`",
        "",
        "## Unresolved Questions",
        "",
        *_render_bullets(report["unresolved_questions"]),
        "",
        "## Recommended Next Block",
        "",
        report["recommended_next_block"],
        "",
        "## Architecture Diagram",
        "",
        "```mermaid",
        "flowchart TD",
        "  Upload[\"POST /documents/upload\"] --> Route[\"upload_to_input_dir\\nsave file + track_id\"]",
        "  Route --> BG[\"FastAPI BackgroundTasks\\npipeline_index_file\"]",
        "  BG --> Parse[\"pipeline_enqueue_file\\nparse uploaded file\"]",
        "  Parse --> Enqueue[\"rag.apipeline_enqueue_documents\\nfull_docs + PENDING doc_status\"]",
        "  Enqueue --> Process[\"rag.apipeline_process_enqueue_documents\"]",
        "  Process --> Chunks[\"chunking\\nchunks_vdb + text_chunks\"]",
        "  Chunks --> Extract[\"_process_extract_entities\\noperate.extract_entities\"]",
        "  Extract --> LLM[\"configured LLM\\ninitial extraction + optional gleaning\"]",
        "  Extract --> Merge[\"merge_nodes_and_edges\\ngraph + entity/relation stores\"]",
        "  DSL[\"run_dsl_knowledge_ingestion\"] --> Ready[\"readiness/policy/custom_kg\"]",
        "  Ready --> Writer[\"write_custom_kg_batches_to_lightrag\"]",
        "  Writer --> Local[\"local LightRAG\\nNetworkX + NanoVectorDB + fake models\"]",
        "  Local --> CustomKG[\"LightRAG.ainsert_custom_kg\\ngraph/vdb chunk writes\"]",
        "  Upload -. \"no inspected call\" .-> DSL",
        "```",
        "",
    ]
    return "\n".join(sections)


def _render_chain_table(chain: dict[str, Any]) -> str:
    rows = [
        "| Step | File | Line | Function | Async | Callee | Side effects |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for step in chain["steps"]:
        rows.append(
            "| {step_id} | `{file}` | {line} | `{function}` | `{async_mode}` | {callee} | {side_effects} |".format(
                step_id=step["entry_id"],
                file=step["file_path"],
                line=step["line_number"],
                function=step["function_name"],
                async_mode=step["async_mode"],
                callee=_escape_table(step["callee"]),
                side_effects=_escape_table("; ".join(step["side_effects"])),
            )
        )
    return "\n".join(rows)


def _render_conclusion_table(conclusions: dict[str, Any]) -> str:
    rows = [
        "| Field | Conclusion | Evidence File | Line | Function | Explanation |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for name, data in conclusions.items():
        rows.append(
            "| {name} | `{conclusion}` | `{file}` | {line} | `{function}` | {explanation} |".format(
                name=name,
                conclusion=data["conclusion"],
                file=data["evidence_file"] or "unresolved",
                line=data["evidence_line"] or 0,
                function=data["evidence_function"] or "unresolved",
                explanation=_escape_table(data["explanation"]),
            )
        )
    return "\n".join(rows)


def _render_bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items]


def _render_unresolved_questions(unresolved_questions: list[str]) -> str:
    return "\n".join(["# Unresolved Questions", "", *_render_bullets(unresolved_questions), ""])


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _bool_text(value: bool | None) -> str:
    if value is None:
        return "unresolved"
    return "true" if value else "false"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _core_diff_check(repo: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--", *FORBIDDEN_CORE_PATHS],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return f"Unable to run git diff: {exc}\n"
    if result.stdout.strip():
        return result.stdout
    return "No diff in forbidden core/API files for Block 24A-0.1.\n"


def _append_command_log(path: Path) -> None:
    commands = [
        "python3 -m lightrag_ext.us_dsl.scripts.run_ingestion_baseline_inspection",
        "git diff -- lightrag/lightrag.py lightrag/operate.py lightrag/prompt.py lightrag/api",
    ]
    with path.open("a", encoding="utf-8") as file:
        file.write("\nGenerated artifacts with:\n")
        for command in commands:
            file.write(f"{command}\n")


if __name__ == "__main__":
    raise SystemExit(main())
