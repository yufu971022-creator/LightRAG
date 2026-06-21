from __future__ import annotations

from pathlib import Path

from .ingestion_baseline_types import IngestionCallChain, IngestionEntry


DOCUMENT_ROUTES = Path("lightrag/api/routers/document_routes.py")
LIGHTRAG_CORE = Path("lightrag/lightrag.py")
OPERATE = Path("lightrag/operate.py")
DSL_INGESTION = Path("lightrag_ext/us_dsl/dsl_knowledge_ingestion.py")
DSL_READINESS = Path("lightrag_ext/us_dsl/dsl_knowledge_ingestion_readiness.py")
DSL_POLICY = Path("lightrag_ext/us_dsl/dsl_knowledge_ingestion_policy.py")
DSL_WRITER = Path("lightrag_ext/us_dsl/dsl_knowledge_ingestion_writer.py")
DSL_SMOKE = Path("lightrag_ext/us_dsl/kg_real_graph_smoke.py")


def inspect_original_upload_chain(repo_path: str | Path) -> IngestionCallChain:
    repo = Path(repo_path)
    steps = [
        _entry(
            repo,
            entry_id="raw-01-upload-route",
            route_or_function="POST /documents/upload",
            file_path=DOCUMENT_ROUTES,
            pattern='"/upload", response_model=InsertResponse',
            function_name="upload_to_input_dir",
            async_mode=True,
            caller="FastAPI APIRouter(prefix='/documents')",
            callee="background_tasks.add_task(pipeline_index_file, rag, file_path, track_id)",
            inputs={
                "file": "UploadFile",
                "safe_filename": "sanitize_filename(file.filename, doc_manager.input_dir)",
                "file_path": "doc_manager.input_dir / safe_filename",
                "track_id": "generate_track_id('upload')",
            },
            outputs={"http": "InsertResponse(status='success', track_id=track_id)"},
            side_effects=[
                "Streams upload bytes to input_dir before returning HTTP 200.",
                "Checks filename duplicate through rag.doc_status.get_doc_by_file_path.",
                "Schedules background processing through FastAPI BackgroundTasks.",
            ],
        ),
        _entry(
            repo,
            entry_id="raw-02-background-index-file",
            route_or_function="pipeline_index_file",
            file_path=DOCUMENT_ROUTES,
            pattern="async def pipeline_index_file",
            function_name="pipeline_index_file",
            async_mode=True,
            caller="FastAPI BackgroundTasks",
            callee="pipeline_enqueue_file(...); rag.apipeline_process_enqueue_documents()",
            inputs={"rag": "LightRAG", "file_path": "Path", "track_id": "str | None"},
            outputs={"success": "No return value; logs errors"},
            side_effects=[
                "Runs after upload response in background task.",
                "Processes queue only if pipeline_enqueue_file succeeds.",
            ],
        ),
        _entry(
            repo,
            entry_id="raw-03-parser-enqueue-file",
            route_or_function="pipeline_enqueue_file",
            file_path=DOCUMENT_ROUTES,
            pattern="async def pipeline_enqueue_file",
            function_name="pipeline_enqueue_file",
            async_mode=True,
            caller="pipeline_index_file / pipeline_index_files",
            callee="rag.apipeline_enqueue_documents(content, file_paths=file_path.name, track_id=track_id)",
            inputs={
                "file_path": "saved upload path",
                "parser": "extension switch: text decode, pypdf/docling, python-docx, pptx, openpyxl",
            },
            outputs={"tuple": "(success: bool, track_id: str)"},
            side_effects=[
                "Reads file bytes and extracts text.",
                "Writes file extraction failures through rag.apipeline_enqueue_error_documents.",
                "Moves successfully enqueued file to __enqueued__.",
            ],
        ),
        _entry(
            repo,
            entry_id="raw-04-full-docs-and-pending-status",
            route_or_function="LightRAG.apipeline_enqueue_documents",
            file_path=LIGHTRAG_CORE,
            pattern="async def apipeline_enqueue_documents",
            function_name="apipeline_enqueue_documents",
            async_mode=True,
            caller="pipeline_enqueue_file / ainsert / pipeline_index_texts",
            callee="self.full_docs.upsert(...); self.doc_status.upsert(...)",
            inputs={
                "input": "document text(s)",
                "ids": "optional document IDs",
                "file_paths": "source filename(s)",
                "track_id": "upload/insert/enqueue track id",
            },
            outputs={"track_id": "returns track_id after enqueue"},
            side_effects=[
                "Computes doc_id from content hash when ids are absent.",
                "Writes original text to full_docs.",
                "Writes doc_status=PENDING with file_path and track_id.",
                "Writes duplicate attempts as doc_status=FAILED.",
            ],
        ),
        _entry(
            repo,
            entry_id="raw-05-process-pending-queue",
            route_or_function="LightRAG.apipeline_process_enqueue_documents",
            file_path=LIGHTRAG_CORE,
            pattern="async def apipeline_process_enqueue_documents",
            function_name="apipeline_process_enqueue_documents",
            async_mode=True,
            caller="pipeline_index_file / scan / text insert / reprocess",
            callee="chunking_func; chunks_vdb.upsert; text_chunks.upsert; _process_extract_entities; merge_nodes_and_edges",
            inputs={
                "doc_statuses": "PROCESSING, FAILED, PENDING",
                "queue_lock": "pipeline_status namespace lock",
            },
            outputs={"state": "doc_status PROCESSING/PROCESSED/FAILED"},
            side_effects=[
                "Uses pipeline_status busy/request_pending as queue gate.",
                "Reads original content from full_docs.",
                "Writes doc_status=PROCESSING before extraction.",
                "Writes chunks_vdb and text_chunks before entity extraction.",
                "Writes doc_status=PROCESSED after graph merge, FAILED on exception.",
            ],
        ),
        _entry(
            repo,
            entry_id="raw-06-entity-extraction",
            route_or_function="LightRAG._process_extract_entities",
            file_path=LIGHTRAG_CORE,
            pattern="async def _process_extract_entities",
            function_name="_process_extract_entities",
            async_mode=True,
            caller="apipeline_process_enqueue_documents",
            callee="operate.extract_entities(..., llm_response_cache=self.llm_response_cache, text_chunks_storage=self.text_chunks)",
            inputs={"chunks": "chunk dict with content/full_doc_id/file_path"},
            outputs={"chunk_results": "list[(maybe_nodes, maybe_edges)]"},
            side_effects=[
                "Calls raw native LLM extraction path.",
                "May update chunk llm_cache_list through text_chunks storage.",
            ],
        ),
        _entry(
            repo,
            entry_id="raw-07-llm-extract-and-gleaning",
            route_or_function="operate.extract_entities",
            file_path=OPERATE,
            pattern="async def extract_entities",
            function_name="extract_entities",
            async_mode=True,
            caller="LightRAG._process_extract_entities",
            callee="use_llm_func_with_cache for initial extraction and one optional gleaning request",
            inputs={
                "chunks": "text chunk dict",
                "global_config.llm_model_func": "runtime LLM function",
                "entity_extract_max_gleaning": "MAX_GLEANING/default, but implementation gates one extra request",
            },
            outputs={"chunk_results": "extracted entity/relation fragments"},
            side_effects=[
                "Calls LLM for initial extraction unless cache hits.",
                "If entity_extract_max_gleaning > 0, performs at most one additional gleaning request.",
                "Caches extract responses when enabled.",
            ],
        ),
        _entry(
            repo,
            entry_id="raw-08-merge-graph-and-vdb",
            route_or_function="operate.merge_nodes_and_edges",
            file_path=OPERATE,
            pattern="async def merge_nodes_and_edges",
            function_name="merge_nodes_and_edges",
            async_mode=True,
            caller="LightRAG.apipeline_process_enqueue_documents",
            callee="_merge_nodes_then_upsert; _merge_edges_then_upsert; full_entities_storage.upsert; full_relations_storage.upsert",
            inputs={"chunk_results": "extracted fragments", "doc_id": "full document id"},
            outputs={"state": "graph/vdb/full entity relation indexes updated"},
            side_effects=[
                "Upserts graph nodes and edges.",
                "Upserts entities_vdb and relationships_vdb.",
                "Writes full_entities and full_relations per doc.",
                "May call LLM summarization during merge when description merge threshold is exceeded.",
            ],
        ),
    ]
    evidence = [
        _evidence(repo, DOCUMENT_ROUTES, '"/upload", response_model=InsertResponse'),
        _evidence(repo, DOCUMENT_ROUTES, "background_tasks.add_task(pipeline_index_file"),
        _evidence(repo, DOCUMENT_ROUTES, "await rag.apipeline_enqueue_documents"),
        _evidence(repo, DOCUMENT_ROUTES, "await rag.apipeline_process_enqueue_documents()"),
        _evidence(repo, LIGHTRAG_CORE, "await self.full_docs.upsert(full_docs_data)"),
        _evidence(repo, LIGHTRAG_CORE, '"status": DocStatus.PENDING'),
        _evidence(repo, LIGHTRAG_CORE, "self.chunks_vdb.upsert(chunks)"),
        _evidence(repo, LIGHTRAG_CORE, "self.text_chunks.upsert(chunks)"),
        _evidence(repo, LIGHTRAG_CORE, "self._process_extract_entities"),
        _evidence(repo, LIGHTRAG_CORE, "await merge_nodes_and_edges"),
        _evidence(repo, OPERATE, "final_result, timestamp = await use_llm_func_with_cache"),
        _evidence(repo, OPERATE, "if entity_extract_max_gleaning > 0:"),
    ]
    return IngestionCallChain(
        chain_name="original_upload_call_chain",
        entry_point="/documents/upload",
        steps=steps,
        final_storage_targets=[
            "full_docs",
            "doc_status",
            "text_chunks",
            "chunks_vdb",
            "chunk_entity_relation_graph",
            "entities_vdb",
            "relationships_vdb",
            "full_entities",
            "full_relations",
            "entity_chunks",
            "relation_chunks",
            "llm_response_cache",
        ],
        calls_embedding=True,
        calls_llm=True,
        calls_extract_entities=True,
        calls_ainsert_custom_kg=False,
        writes_full_docs=True,
        writes_text_chunks=True,
        writes_doc_status=True,
        writes_graph=True,
        evidence=evidence,
    )


def inspect_dsl_ingestion_chain(repo_path: str | Path) -> IngestionCallChain:
    repo = Path(repo_path)
    steps = [
        _entry(
            repo,
            entry_id="dsl-01-entry",
            route_or_function="run_dsl_knowledge_ingestion",
            file_path=DSL_INGESTION,
            pattern="def run_dsl_knowledge_ingestion",
            function_name="run_dsl_knowledge_ingestion",
            async_mode=False,
            caller="Explicit DSL tooling/tests/scripts",
            callee="run_ingestion_readiness_gate / run_canary_dsl_knowledge_ingestion / run_module_level_dsl_knowledge_ingestion",
            inputs={"config": "DslKnowledgeIngestionConfig.from_env() unless supplied"},
            outputs={"report": "DslKnowledgeIngestionReport"},
            side_effects=["No write in readiness mode.", "Canary/module may call writer if gates pass."],
        ),
        _entry(
            repo,
            entry_id="dsl-02-readiness",
            route_or_function="run_ingestion_readiness_gate",
            file_path=DSL_READINESS,
            pattern="def run_ingestion_readiness_gate",
            function_name="run_ingestion_readiness_gate",
            async_mode=False,
            caller="run_dsl_knowledge_ingestion",
            callee="build_module_ingestion_payload; prepare_policy_approved_ingestion_payload",
            inputs={"source_path/module_name/dsl_payload": "DSL payload source"},
            outputs={"report": "readiness report with ready_to_write"},
            side_effects=["Builds and validates custom_kg artifacts in memory."],
        ),
        _entry(
            repo,
            entry_id="dsl-03-sidecar-and-custom-kg",
            route_or_function="prepare_policy_approved_ingestion_payload",
            file_path=DSL_POLICY,
            pattern="def prepare_policy_approved_ingestion_payload",
            function_name="prepare_policy_approved_ingestion_payload",
            async_mode=False,
            caller="run_ingestion_readiness_gate / build_readiness_artifacts",
            callee="build_metadata_sidecar_records; to_lightrag_custom_kg_input; build_graph_insert_sidecar_records",
            inputs={"payload": "DslKgPayload", "namespace": "config.namespace"},
            outputs={"prepared": "PreparedIngestionPayload(custom_kg_input, sidecar_records, rollback info)"},
            side_effects=[
                "Builds full sidecar records and graph-insert sidecar records in memory.",
                "Does not persist sidecar records in dsl_knowledge_ingestion_writer.",
            ],
        ),
        _entry(
            repo,
            entry_id="dsl-04-batching",
            route_or_function="split_custom_kg_batches",
            file_path=DSL_INGESTION,
            pattern="def split_custom_kg_batches",
            function_name="split_custom_kg_batches",
            async_mode=False,
            caller="run_canary_dsl_knowledge_ingestion / run_module_level_dsl_knowledge_ingestion",
            callee="write_custom_kg_batches_to_lightrag",
            inputs={"custom_kg": "prepared.custom_kg_input", "batch_size": "config.batch_size"},
            outputs={"batches": "list[custom_kg batch]"},
            side_effects=[],
        ),
        _entry(
            repo,
            entry_id="dsl-05-writer",
            route_or_function="write_custom_kg_batches_to_lightrag",
            file_path=DSL_WRITER,
            pattern="def write_custom_kg_batches_to_lightrag",
            function_name="write_custom_kg_batches_to_lightrag",
            async_mode=False,
            caller="DSL canary/module ingestion",
            callee="without_graph_remote_env; asyncio.run(_write_batches_async(...))",
            inputs={"custom_kg_batches": "list[dict]", "config": "DslKnowledgeIngestionConfig"},
            outputs={"write_result": "WriteResult"},
            side_effects=[
                "Blocks production namespace/Neo4j/non-fake-model use through guard issues.",
                "Optionally isolates remote graph env before local write.",
            ],
        ),
        _entry(
            repo,
            entry_id="dsl-06-local-lightrag-construction",
            route_or_function="_write_batches_in_working_dir",
            file_path=DSL_WRITER,
            pattern="async def _write_batches_in_working_dir",
            function_name="_write_batches_in_working_dir",
            async_mode=True,
            caller="_write_batches_async",
            callee="LightRAG(... local stores, fake embedding, fake LLM); rag.ainsert_custom_kg",
            inputs={
                "working_dir": "config.working_dir or temp directory",
                "workspace": "config.namespace",
                "graph_storage": "NetworkXStorage",
                "embedding": "8-dim dsl-test-fake-embedding",
                "llm": "_fake_llm",
            },
            outputs={"result": "working_dir, batch results, called flag"},
            side_effects=[
                "Creates/uses a test-scoped local working_dir.",
                "Initializes local LightRAG storages.",
                "Calls ainsert_custom_kg for each batch.",
            ],
        ),
        _entry(
            repo,
            entry_id="dsl-07-custom-kg-core-write",
            route_or_function="LightRAG.ainsert_custom_kg",
            file_path=LIGHTRAG_CORE,
            pattern="async def ainsert_custom_kg",
            function_name="ainsert_custom_kg",
            async_mode=True,
            caller="dsl_knowledge_ingestion_writer._write_batches_in_working_dir",
            callee="chunks_vdb.upsert; text_chunks.upsert; graph upsert_nodes_batch/upsert_edges_batch; entities_vdb.upsert; relationships_vdb.upsert",
            inputs={"custom_kg": "chunks/entities/relationships", "full_doc_id": "config.namespace"},
            outputs={"state": "custom KG inserted into local storages"},
            side_effects=[
                "Writes chunks_vdb and text_chunks.",
                "Writes graph nodes and relationships.",
                "Writes entities_vdb and relationships_vdb.",
                "Does not call extract_entities.",
                "Does not write full_docs or doc_status.",
            ],
        ),
    ]
    evidence = [
        _evidence(repo, DSL_INGESTION, "def run_dsl_knowledge_ingestion"),
        _evidence(repo, DSL_INGESTION, "write_custom_kg_batches_to_lightrag(batches"),
        _evidence(repo, DSL_WRITER, "with without_graph_remote_env():"),
        _evidence(repo, DSL_WRITER, "workspace=config.namespace"),
        _evidence(repo, DSL_WRITER, 'embedding_dim=8'),
        _evidence(repo, DSL_WRITER, 'model_name="dsl-test-fake-embedding"'),
        _evidence(repo, DSL_WRITER, "llm_model_func=_fake_llm"),
        _evidence(repo, DSL_WRITER, "await rag.ainsert_custom_kg(custom_kg, full_doc_id=config.namespace)"),
        _evidence(repo, LIGHTRAG_CORE, "async def ainsert_custom_kg"),
        _evidence(repo, LIGHTRAG_CORE, "self.chunks_vdb.upsert(all_chunks_data)"),
        _evidence(repo, LIGHTRAG_CORE, "self.text_chunks.upsert(all_chunks_data)"),
        _evidence(repo, LIGHTRAG_CORE, "self.chunk_entity_relation_graph.upsert_nodes_batch"),
        _evidence(repo, LIGHTRAG_CORE, "self.chunk_entity_relation_graph.upsert_edges_batch"),
    ]
    return IngestionCallChain(
        chain_name="dsl_ingestion_call_chain",
        entry_point="run_dsl_knowledge_ingestion",
        steps=steps,
        final_storage_targets=[
            "text_chunks",
            "chunks_vdb",
            "chunk_entity_relation_graph",
            "entities_vdb",
            "relationships_vdb",
        ],
        calls_embedding=True,
        calls_llm=False,
        calls_extract_entities=False,
        calls_ainsert_custom_kg=True,
        writes_full_docs=False,
        writes_text_chunks=True,
        writes_doc_status=False,
        writes_graph=True,
        evidence=evidence,
    )


def inspect_router_status(repo_path: str | Path) -> dict[str, bool]:
    repo = Path(repo_path)
    core_py = {
        "lightrag/lightrag.py": _read(repo / LIGHTRAG_CORE),
        "lightrag/operate.py": _read(repo / OPERATE),
    }
    upload_text = _read(repo / DOCUMENT_ROUTES)
    api_text = upload_text
    native_text = "\n".join([api_text, *core_py.values()])
    return {
        "upload_calls_dsl": any(
            token in upload_text
            for token in (
                "run_dsl_knowledge_ingestion",
                "ainsert_with_dsl",
                "lightrag_ext.us_dsl",
                "DslAwarePipelineHook",
            )
        ),
        "auto_router_exists": any(
            token in native_text
            for token in (
                "ingestion_mode",
                "AUTO_INGESTION",
                "auto_ingestion",
                "shadow",
                "raw_ingestion",
            )
        ),
        "domain_auto_dsl": "default_domain_registry" in api_text
        or "DomainRegistry" in api_text,
        "dsl_fallback_to_raw_in_api": "fallback_to_original" in api_text
        or "ainsert_with_dsl_dry_run" in api_text,
        "same_file_calls_both_in_upload": "ainsert_custom_kg" in upload_text
        and ("apipeline_enqueue_documents" in upload_text or ".ainsert(" in upload_text),
    }


def inspect_dsl_extract_usage(repo_path: str | Path) -> dict[str, bool]:
    repo = Path(repo_path)
    dsl_chain_text = "\n".join(
        _read(repo / path)
        for path in [DSL_INGESTION, DSL_READINESS, DSL_POLICY, DSL_WRITER]
    )
    return {
        "run_dsl_chain_calls_extract_entities": "extract_entities(" in dsl_chain_text
        or "native_extract_entities(" in dsl_chain_text,
        "run_dsl_chain_calls_ainsert_custom_kg": "ainsert_custom_kg" in dsl_chain_text,
    }


def _entry(
    repo: Path,
    *,
    entry_id: str,
    route_or_function: str,
    file_path: Path,
    pattern: str,
    function_name: str,
    async_mode: bool,
    caller: str,
    callee: str,
    inputs: dict,
    outputs: dict,
    side_effects: list[str],
) -> IngestionEntry:
    return IngestionEntry(
        entry_id=entry_id,
        route_or_function=route_or_function,
        file_path=str(file_path),
        line_number=_line_number(repo / file_path, pattern),
        function_name=function_name,
        async_mode=async_mode,
        caller=caller,
        callee=callee,
        inputs=inputs,
        outputs=outputs,
        side_effects=side_effects,
    )


def _line_number(path: Path, pattern: str) -> int:
    for index, line in enumerate(_read(path).splitlines(), start=1):
        if pattern in line:
            return index
    return 0


def _evidence(repo: Path, file_path: Path, pattern: str) -> str:
    line = _line_number(repo / file_path, pattern)
    if line == 0:
        return f"{file_path}:unresolved pattern={pattern!r}"
    return f"{file_path}:{line} pattern={pattern!r}"


def _read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")

