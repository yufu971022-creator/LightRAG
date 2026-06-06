from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from .dsl_knowledge_ingestion_types import DslKnowledgeIngestionConfig
from .kg_real_graph_smoke import (
    SMOKE_GRAPH_STORAGE,
    _SimpleTokenizer,
    _fake_embedding,
    _fake_llm,
    without_graph_remote_env,
)


LOCAL_STORAGE_TYPES = {
    "kv_storage": "JsonKVStorage",
    "vector_storage": "NanoVectorDBStorage",
    "graph_storage": SMOKE_GRAPH_STORAGE,
    "doc_status_storage": "JsonDocStatusStorage",
}


@dataclass(frozen=True)
class WriteBatchResult:
    batch_index: int
    chunk_count: int
    entity_count: int
    relationship_count: int
    status: str
    error: str | None = None


@dataclass
class WriteResult:
    __test__: ClassVar[bool] = False

    enabled: bool
    skipped: bool
    skip_reason: str | None
    working_dir: str | None
    namespace: str
    batch_count: int
    failed_batch_count: int
    ainsert_custom_kg_called: bool
    graph_write_attempted: bool
    graph_write_succeeded: bool
    neo4j_connected: bool
    production_write: bool
    formal_graph_written: bool
    cleanup_passed: bool
    rollback_passed: bool
    elapsed_ms: int
    batches: list[WriteBatchResult] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommended_next_step: str = ""


def write_custom_kg_batches_to_lightrag(
    custom_kg_batches: list[dict[str, list[dict[str, Any]]]],
    *,
    config: DslKnowledgeIngestionConfig,
) -> WriteResult:
    started = time.monotonic()
    if not config.enabled:
        return _result(
            config,
            skipped=True,
            skip_reason="Feature flag enable_dsl_aware_knowledge_ingestion is disabled.",
            elapsed_ms=_elapsed_ms(started),
            recommended_next_step="ENABLE_DSL_KNOWLEDGE_INGESTION",
        )
    guard_issues = _guard_issues(config, custom_kg_batches)
    if guard_issues:
        return _result(
            config,
            skipped=True,
            skip_reason=str(guard_issues[0]["code"]),
            elapsed_ms=_elapsed_ms(started),
            issues=guard_issues,
            recommended_next_step="FIX_INGESTION_WRITE_GOVERNANCE",
        )
    if not custom_kg_batches:
        return _result(
            config,
            skipped=True,
            skip_reason="NO_CUSTOM_KG_BATCHES_TO_WRITE",
            elapsed_ms=_elapsed_ms(started),
            recommended_next_step="FIX_READINESS_GATE",
        )

    try:
        if config.isolate_remote_graph_env:
            with without_graph_remote_env():
                result = asyncio.run(
                    asyncio.wait_for(
                        _write_batches_async(custom_kg_batches, config=config),
                        timeout=config.timeout_seconds,
                    )
                )
        else:
            result = asyncio.run(
                asyncio.wait_for(
                    _write_batches_async(custom_kg_batches, config=config),
                    timeout=config.timeout_seconds,
                )
            )
    except TimeoutError:
        cleanup_passed = _cleanup_path(config.working_dir) if config.cleanup_after_run else True
        return _result(
            config,
            skipped=False,
            skip_reason="TIMEOUT",
            batch_count=len(custom_kg_batches),
            failed_batch_count=1,
            ainsert_custom_kg_called=True,
            graph_write_attempted=True,
            graph_write_succeeded=False,
            cleanup_passed=cleanup_passed,
            rollback_passed=False,
            elapsed_ms=_elapsed_ms(started),
            issues=[_issue("TIMEOUT", "DSL knowledge ingestion timed out.")],
            recommended_next_step="FIX_CANARY_INGESTION",
        )
    except Exception as exc:
        cleanup_passed = _cleanup_path(config.working_dir) if config.cleanup_after_run else True
        issue_code = (
            "NEO4J_BLOCKED"
            if "neo4j" in str(exc).lower()
            else "LIGHTRAG_CUSTOM_KG_WRITE_FAILED"
        )
        return _result(
            config,
            skipped=False,
            skip_reason=issue_code,
            batch_count=len(custom_kg_batches),
            failed_batch_count=1,
            ainsert_custom_kg_called=True,
            graph_write_attempted=True,
            graph_write_succeeded=False,
            cleanup_passed=cleanup_passed,
            rollback_passed=False,
            elapsed_ms=_elapsed_ms(started),
            issues=[_issue(issue_code, f"{type(exc).__name__}: {exc}")],
            recommended_next_step="FIX_CANARY_INGESTION",
        )

    failed_count = sum(1 for batch in result["batches"] if batch.status != "SUCCESS")
    return _result(
        config,
        skipped=False,
        skip_reason=None if failed_count == 0 else "BATCH_WRITE_FAILED",
        working_dir=result["working_dir"],
        batch_count=len(custom_kg_batches),
        failed_batch_count=failed_count,
        ainsert_custom_kg_called=bool(result["called"]),
        graph_write_attempted=bool(result["called"]),
        graph_write_succeeded=failed_count == 0,
        cleanup_passed=bool(result["cleanup_passed"]),
        rollback_passed=bool(result["rollback_passed"]),
        elapsed_ms=_elapsed_ms(started),
        batches=list(result["batches"]),
        recommended_next_step=(
            "MODULE_TEST_GRAPH_INGESTION_READY"
            if failed_count == 0
            else "FIX_CANARY_INGESTION"
        ),
    )


async def _write_batches_async(
    custom_kg_batches: list[dict[str, list[dict[str, Any]]]],
    *,
    config: DslKnowledgeIngestionConfig,
) -> dict[str, Any]:
    if config.working_dir:
        working_dir = config.working_dir
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        result = await _write_batches_in_working_dir(
            custom_kg_batches,
            config=config,
            working_dir=working_dir,
        )
        cleanup_passed = False
        if config.cleanup_after_run:
            cleanup_passed = _cleanup_path(working_dir)
        result["cleanup_passed"] = cleanup_passed
        result["rollback_passed"] = (
            cleanup_passed if config.rollback_after_run else True
        )
        return result

    if config.cleanup_after_run:
        temp_dir_value = ""
        with tempfile.TemporaryDirectory(prefix="lightrag_dsl_ingestion_dsl_test_") as temp_dir:
            temp_dir_value = temp_dir
            result = await _write_batches_in_working_dir(
                custom_kg_batches,
                config=config,
                working_dir=temp_dir,
            )
        result["cleanup_passed"] = not Path(temp_dir_value).exists()
        result["rollback_passed"] = (
            result["cleanup_passed"] if config.rollback_after_run else True
        )
        return result

    working_dir = tempfile.mkdtemp(prefix="lightrag_dsl_ingestion_dsl_test_")
    result = await _write_batches_in_working_dir(
        custom_kg_batches,
        config=config,
        working_dir=working_dir,
    )
    result["cleanup_passed"] = False
    result["rollback_passed"] = True
    return result


async def _write_batches_in_working_dir(
    custom_kg_batches: list[dict[str, list[dict[str, Any]]]],
    *,
    config: DslKnowledgeIngestionConfig,
    working_dir: str,
) -> dict[str, Any]:
    if not _is_safe_working_dir(working_dir):
        raise RuntimeError(f"Unsafe working_dir: {working_dir}")

    rag = None
    batch_results: list[WriteBatchResult] = []
    called = False
    try:
        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc, Tokenizer

        rag = LightRAG(
            working_dir=working_dir,
            workspace=config.namespace,
            kv_storage=LOCAL_STORAGE_TYPES["kv_storage"],
            vector_storage=LOCAL_STORAGE_TYPES["vector_storage"],
            graph_storage=SMOKE_GRAPH_STORAGE,
            doc_status_storage=LOCAL_STORAGE_TYPES["doc_status_storage"],
            tokenizer=Tokenizer(
                model_name="dsl-test-simple-tokenizer",
                tokenizer=_SimpleTokenizer(),
            ),
            embedding_func=EmbeddingFunc(
                embedding_dim=8,
                max_token_size=8192,
                func=_fake_embedding,
                model_name="dsl-test-fake-embedding",
                supports_asymmetric=True,
            ),
            llm_model_func=_fake_llm,
        )
        await rag.initialize_storages()
        for index, custom_kg in enumerate(custom_kg_batches):
            try:
                called = True
                await rag.ainsert_custom_kg(custom_kg, full_doc_id=config.namespace)
                batch_results.append(_batch_result(index, custom_kg, "SUCCESS"))
            except Exception as exc:
                batch_results.append(
                    _batch_result(index, custom_kg, "FAILED", error=str(exc))
                )
                break
    finally:
        if rag is not None:
            await rag.finalize_storages()

    return {
        "working_dir": working_dir,
        "batches": batch_results,
        "called": called,
        "cleanup_passed": True,
        "rollback_passed": True,
    }


def _guard_issues(
    config: DslKnowledgeIngestionConfig,
    batches: list[dict[str, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if config.allow_production or not config.test_namespace_only:
        issues.append(_issue("PRODUCTION_WRITE_BLOCKED", "Production writes are disabled."))
    if not _safe_namespace(config.namespace):
        issues.append(_issue("PRODUCTION_NAMESPACE_BLOCKED", "Namespace must be test-scoped."))
    if config.target_graph_type != "test_graph":
        issues.append(_issue("FORMAL_GRAPH_BLOCKED", "Only test_graph writes are allowed."))
    if config.allow_neo4j:
        issues.append(_issue("NEO4J_BLOCKED", "Neo4j is not allowed for this pipeline."))
    if not config.force_local_graph_storage:
        issues.append(_issue("LOCAL_GRAPH_STORAGE_REQUIRED", "Local graph storage is required."))
    if not config.use_fake_embedding or not config.use_fake_llm:
        issues.append(_issue("FAKE_MODEL_REQUIRED", "Fake embedding and LLM are required."))
    if not config.explicit_local_tokenizer:
        issues.append(_issue("LOCAL_TOKENIZER_REQUIRED", "Explicit local tokenizer is required."))
    if config.working_dir and not _is_safe_working_dir(config.working_dir):
        issues.append(_issue("UNSAFE_WORKING_DIR_BLOCKED", "Working directory is not test-scoped."))
    for batch in batches:
        issues.extend(_custom_kg_guard_issues(batch))
    return issues


def _custom_kg_guard_issues(
    custom_kg: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    entity_names = {str(item.get("entity_name")) for item in custom_kg.get("entities", [])}
    chunk_ids = {str(item.get("source_id")) for item in custom_kg.get("chunks", [])}
    blocked_tokens = {
        "ReviewRequired",
        "InfoOnly",
        "VersionReviewRequired",
        "VersionConflictWith",
        "MissingEvidence",
        "InvalidRelation",
    }
    for entity in custom_kg.get("entities", []):
        if str(entity.get("source_id")) not in chunk_ids:
            issues.append(_issue("ENTITY_SOURCE_CHUNK_MISSING", "Entity source_id has no chunk."))
        text = f"{entity.get('entity_type')} {entity.get('description')}"
        if any(token in text for token in blocked_tokens):
            issues.append(_issue("UNSAFE_ENTITY_BLOCKED", "Unsafe entity token found."))
    for relationship in custom_kg.get("relationships", []):
        if str(relationship.get("source_id")) not in chunk_ids:
            issues.append(_issue("RELATION_SOURCE_CHUNK_MISSING", "Relation source_id has no chunk."))
        if relationship.get("src_id") not in entity_names or relationship.get("tgt_id") not in entity_names:
            issues.append(_issue("DANGLING_RELATIONSHIP_BLOCKED", "Relation endpoint missing."))
        text = f"{relationship.get('keywords')} {relationship.get('description')}"
        if any(token in text for token in blocked_tokens):
            issues.append(_issue("UNSAFE_RELATIONSHIP_BLOCKED", "Unsafe relationship token found."))
    return issues


def _batch_result(
    index: int,
    custom_kg: dict[str, list[dict[str, Any]]],
    status: str,
    *,
    error: str | None = None,
) -> WriteBatchResult:
    return WriteBatchResult(
        batch_index=index,
        chunk_count=len(custom_kg.get("chunks", [])),
        entity_count=len(custom_kg.get("entities", [])),
        relationship_count=len(custom_kg.get("relationships", [])),
        status=status,
        error=error,
    )


def _result(
    config: DslKnowledgeIngestionConfig,
    *,
    skipped: bool,
    skip_reason: str | None,
    elapsed_ms: int,
    working_dir: str | None = None,
    batch_count: int = 0,
    failed_batch_count: int = 0,
    ainsert_custom_kg_called: bool = False,
    graph_write_attempted: bool = False,
    graph_write_succeeded: bool = False,
    cleanup_passed: bool = True,
    rollback_passed: bool = True,
    batches: list[WriteBatchResult] | None = None,
    issues: list[dict[str, Any]] | None = None,
    recommended_next_step: str = "",
) -> WriteResult:
    return WriteResult(
        enabled=config.enabled,
        skipped=skipped,
        skip_reason=skip_reason,
        working_dir=working_dir or config.working_dir,
        namespace=config.namespace,
        batch_count=batch_count,
        failed_batch_count=failed_batch_count,
        ainsert_custom_kg_called=ainsert_custom_kg_called,
        graph_write_attempted=graph_write_attempted,
        graph_write_succeeded=graph_write_succeeded,
        neo4j_connected=False,
        production_write=False,
        formal_graph_written=False,
        cleanup_passed=cleanup_passed,
        rollback_passed=rollback_passed,
        elapsed_ms=elapsed_ms,
        batches=batches or [],
        issues=issues or [],
        recommended_next_step=recommended_next_step,
    )


def _safe_namespace(namespace: str) -> bool:
    lowered = namespace.lower()
    return ("test" in lowered or "dsl_test" in lowered) and lowered not in {
        "prod",
        "production",
        "main",
        "default",
    }


def _is_safe_working_dir(working_dir: str) -> bool:
    path = Path(working_dir).expanduser().resolve()
    lowered = str(path).lower()
    if any(token in lowered for token in ["/prod", "/production", "/ges"]):
        return False
    return (
        (
            "tmp" in lowered
            or "var/folders" in lowered
            or "dsl_test" in lowered
            or "test_graph_workspace" in lowered
        )
        and (
            "lightrag_dsl_ingestion" in lowered
            or "dsl_test" in lowered
            or "test_graph_workspace" in lowered
        )
    )


def _cleanup_path(path: str | None) -> bool:
    if not path:
        return True
    target = Path(path).expanduser().resolve()
    if not target.exists():
        return True
    if not _is_safe_working_dir(str(target)):
        return False
    shutil.rmtree(target, ignore_errors=True)
    return not target.exists()


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": message}


__all__ = [
    "WriteBatchResult",
    "WriteResult",
    "write_custom_kg_batches_to_lightrag",
]
