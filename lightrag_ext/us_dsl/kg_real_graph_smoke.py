from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import numpy as np

from .kg_metadata_sidecar import (
    build_graph_insert_sidecar_records,
    validate_graph_insert_sidecar_alignment,
)
from .kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship
from .kg_test_graph_write import to_lightrag_custom_kg_input


ENABLE_REAL_SMOKE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_REAL_CUSTOM_KG_SMOKE"

SMOKE_SOURCE_ID = "dsl_test_chunk_001"
SMOKE_NAMESPACE = "dsl_test_real_custom_kg_smoke"
SMOKE_WORKSPACE = "dsl_test_real_custom_kg_smoke"
SMOKE_GRAPH_STORAGE = "NetworkXStorage"

_LOCAL_STORAGE_TYPES = {
    "kv_storage": "JsonKVStorage",
    "vector_storage": "NanoVectorDBStorage",
    "graph_storage": SMOKE_GRAPH_STORAGE,
    "doc_status_storage": "JsonDocStatusStorage",
}

REMOTE_GRAPH_ENV_VARS = (
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "NEO4J_DATABASE",
    "NEO4J_USER",
    "NEO4J_PASS",
    "NEO4J_WORKSPACE",
    "GRAPH_STORAGE",
    "LIGHTRAG_GRAPH_STORAGE",
    "AGE_GRAPH_NAME",
    "AGE_DB_NAME",
    "AGE_HOST",
    "AGE_PORT",
    "AGE_USER",
    "AGE_PASSWORD",
)


@dataclass(frozen=True)
class GraphRemoteEnvIsolation:
    isolated_graph_env_count: int
    isolated_keys: tuple[str, ...]


@dataclass
class RealCustomKgSmokeConfig:
    __test__: ClassVar[bool] = False

    enabled: bool = False
    use_temp_working_dir: bool = True
    test_namespace_only: bool = True
    namespace: str = SMOKE_NAMESPACE
    workspace: str = SMOKE_WORKSPACE
    working_dir: str | None = None
    graph_storage_type: str = SMOKE_GRAPH_STORAGE
    max_chunks: int = 1
    max_entities: int = 2
    max_relationships: int = 1
    timeout_seconds: int = 120
    use_fake_embedding: bool = True
    use_fake_llm: bool = True
    allow_neo4j: bool = False
    cleanup_after_run: bool = True
    force_local_graph_storage: bool = True
    local_graph_storage: str = SMOKE_GRAPH_STORAGE
    isolate_remote_graph_env: bool = True
    feature_flag_name: str = "enable_dsl_aware_real_custom_kg_smoke"

    @classmethod
    def from_env(cls) -> "RealCustomKgSmokeConfig":
        return cls(enabled=os.getenv(ENABLE_REAL_SMOKE_ENV) == "1")


@dataclass
class RealGraphSmokeReport:
    __test__: ClassVar[bool] = False

    enabled: bool
    skipped: bool
    skip_reason: str | None
    working_dir: str | None
    workspace: str
    graph_storage_type: str
    custom_kg_chunk_count: int
    custom_kg_entity_count: int
    custom_kg_relationship_count: int
    sidecar_record_count: int
    sidecar_alignment_passed: bool
    ainsert_custom_kg_called: bool
    graph_write_attempted: bool
    graph_write_succeeded: bool
    neo4j_connected: bool
    production_namespace_blocked: bool
    fake_embedding_used: bool
    fake_llm_used: bool
    cleanup_passed: bool
    timeout_seconds: int
    elapsed_ms: int
    isolated_graph_env_count: int
    issues: list[dict[str, Any]] = field(default_factory=list)
    recommended_next_step: str = ""


@contextmanager
def without_graph_remote_env() -> Iterator[GraphRemoteEnvIsolation]:
    original_values: dict[str, str | None] = {
        key: os.environ.get(key) for key in REMOTE_GRAPH_ENV_VARS
    }
    isolated_keys = tuple(key for key, value in original_values.items() if value is not None)
    try:
        for key in REMOTE_GRAPH_ENV_VARS:
            os.environ.pop(key, None)
        os.environ["GRAPH_STORAGE"] = SMOKE_GRAPH_STORAGE
        os.environ["LIGHTRAG_GRAPH_STORAGE"] = SMOKE_GRAPH_STORAGE
        yield GraphRemoteEnvIsolation(
            isolated_graph_env_count=len(isolated_keys),
            isolated_keys=isolated_keys,
        )
    finally:
        for key in REMOTE_GRAPH_ENV_VARS:
            original_value = original_values[key]
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value


def build_minimal_real_smoke_payload() -> DslKgPayload:
    content = (
        "Test source text for DSL-aware graph smoke. "
        "Field Deal Number is a required field."
    )
    metadata = _smoke_metadata(content)
    return DslKgPayload(
        chunks=[
            KgChunk(
                content=content,
                source_id=SMOKE_SOURCE_ID,
                file_path="dsl_test_real_custom_kg_smoke.txt",
                metadata={**metadata, "validationStatus": "CHUNK", "reviewDecision": "CHUNK"},
            )
        ],
        entities=[
            KgEntity(
                entity_name="TestFeature",
                entity_type="FeatureCatalog",
                description="TestFeature is the test feature for DSL graph smoke.",
                source_id=SMOKE_SOURCE_ID,
                metadata={
                    **metadata,
                    "featureKey": "TestFeature",
                    "canonicalTerm": "TestFeature",
                    "originalTerm": "TestFeature",
                },
            ),
            KgEntity(
                entity_name="Deal Number",
                entity_type="FieldSpec",
                description=(
                    "Deal Number is a required field in the test DSL graph smoke source."
                ),
                source_id=SMOKE_SOURCE_ID,
                metadata={
                    **metadata,
                    "canonicalTerm": "Deal Number",
                    "originalTerm": "Deal Number",
                    "candidateId": "dsl-test-entity-deal-number",
                },
            ),
        ],
        relationships=[
            KgRelationship(
                src_id="TestFeature",
                tgt_id="Deal Number",
                description="TestFeature has field Deal Number.",
                keywords="HasFieldSpec",
                source_id=SMOKE_SOURCE_ID,
                weight=1.0,
                metadata={
                    **metadata,
                    "relationType": "HasFieldSpec",
                    "candidateId": "dsl-test-relation-has-field-spec",
                },
            )
        ],
        metadata={"namespace": SMOKE_NAMESPACE, "workspace": SMOKE_WORKSPACE},
        summary={
            "chunk_count": 1,
            "entity_count": 2,
            "relationship_count": 1,
            "graph_write_called": False,
        },
    )


def build_minimal_real_smoke_custom_kg_input() -> dict[str, list[dict[str, Any]]]:
    return to_lightrag_custom_kg_input(
        build_minimal_real_smoke_payload(),
        max_entities=2,
        max_relationships=1,
    )


def run_real_custom_kg_smoke(
    *,
    config: RealCustomKgSmokeConfig | None = None,
) -> RealGraphSmokeReport:
    config = config or RealCustomKgSmokeConfig.from_env()
    started = time.monotonic()
    payload = build_minimal_real_smoke_payload()
    custom_kg = to_lightrag_custom_kg_input(
        payload,
        max_entities=config.max_entities,
        max_relationships=config.max_relationships,
    )
    graph_insert_sidecar = build_graph_insert_sidecar_records(
        payload,
        custom_kg,
        namespace=config.namespace,
    )
    alignment = validate_graph_insert_sidecar_alignment(custom_kg, graph_insert_sidecar)

    base_report = _base_report(
        config,
        custom_kg=custom_kg,
        sidecar_record_count=len(graph_insert_sidecar),
        sidecar_alignment_passed=alignment.pass_status == "PASS",
        started=started,
    )

    if not config.enabled:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="Feature flag enable_dsl_aware_real_custom_kg_smoke is disabled.",
            elapsed_ms=_elapsed_ms(started),
            recommended_next_step="ENABLE_FEATURE_FLAG_TO_TEST_GRAPH_WRITE",
        )
    if not _is_safe_namespace(config.namespace) or not _is_safe_namespace(config.workspace):
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="PRODUCTION_NAMESPACE_BLOCKED",
            production_namespace_blocked=True,
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "PRODUCTION_NAMESPACE_BLOCKED",
                    "namespace and workspace must contain test or dsl_test.",
                )
            ],
            recommended_next_step="DO_NOT_WRITE_GRAPH",
        )
    if config.max_chunks > 1 or config.max_entities > 2 or config.max_relationships > 1:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="SMOKE_LIMIT_EXCEEDED",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "SMOKE_LIMIT_EXCEEDED",
                    "Block 18C permits only 1 chunk, <=2 entities, 1 relationship.",
                )
            ],
            recommended_next_step="FIX_GRAPH_STORAGE_CONFIG",
        )
    if not config.use_fake_embedding or not config.use_fake_llm:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="FAKE_MODEL_REQUIRED",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "FAKE_MODEL_REQUIRED",
                    "Real smoke must use fake embedding and fake LLM.",
                )
            ],
            recommended_next_step="FIX_GRAPH_STORAGE_CONFIG",
        )
    if not config.force_local_graph_storage:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="REAL_GRAPH_STORAGE_UNSUPPORTED",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "REAL_GRAPH_STORAGE_UNSUPPORTED",
                    "Block 18C-1 requires force_local_graph_storage=True.",
                )
            ],
            recommended_next_step="FIX_GRAPH_STORAGE_CONFIG",
        )
    if config.local_graph_storage != SMOKE_GRAPH_STORAGE:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="REAL_GRAPH_STORAGE_UNSUPPORTED",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "REAL_GRAPH_STORAGE_UNSUPPORTED",
                    "Only local NetworkXStorage is supported for Block 18C-1.",
                )
            ],
            recommended_next_step="FIX_GRAPH_STORAGE_CONFIG",
        )
    if (
        not config.allow_neo4j
        and not config.isolate_remote_graph_env
        and _neo4j_config_present(config)
    ):
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="NEO4J_BLOCKED",
            neo4j_connected=False,
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "NEO4J_BLOCKED",
                    "Neo4j config is present but allow_neo4j is false.",
                )
            ],
            recommended_next_step="DO_NOT_WRITE_GRAPH",
        )
    if config.graph_storage_type != SMOKE_GRAPH_STORAGE:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="UNSUPPORTED_GRAPH_STORAGE",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "UNSUPPORTED_GRAPH_STORAGE",
                    "Block 18C only permits local NetworkXStorage.",
                )
            ],
            recommended_next_step="FIX_GRAPH_STORAGE_CONFIG",
        )
    if config.working_dir and not _is_safe_working_dir(config.working_dir):
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="UNSAFE_WORKING_DIR_BLOCKED",
            production_namespace_blocked=True,
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "UNSAFE_WORKING_DIR_BLOCKED",
                    "working_dir must be temporary and test-scoped.",
                )
            ],
            recommended_next_step="DO_NOT_WRITE_GRAPH",
        )
    if alignment.pass_status != "PASS":
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="SIDECAR_ALIGNMENT_FAIL",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "SIDECAR_ALIGNMENT_FAIL",
                    "Graph insert sidecar does not align with custom_kg input.",
                )
            ],
            recommended_next_step="FIX_SIDECAR_ALIGNMENT",
        )

    if not config.working_dir and not config.use_temp_working_dir:
        return _replace_report(
            base_report,
            skipped=True,
            skip_reason="TEMP_WORKING_DIR_REQUIRED",
            elapsed_ms=_elapsed_ms(started),
            issues=[
                _issue(
                    "TEMP_WORKING_DIR_REQUIRED",
                    "Block 18C requires a temp working_dir unless an explicit safe path is provided.",
                )
            ],
            recommended_next_step="FIX_GRAPH_STORAGE_CONFIG",
        )
    isolated_graph_env_count = 0
    try:
        if config.isolate_remote_graph_env:
            with without_graph_remote_env() as isolation:
                isolated_graph_env_count = isolation.isolated_graph_env_count
                result = asyncio.run(
                    asyncio.wait_for(
                        _run_real_custom_kg_smoke_async(config, custom_kg),
                        timeout=config.timeout_seconds,
                    )
                )
        else:
            result = asyncio.run(
                asyncio.wait_for(
                    _run_real_custom_kg_smoke_async(config, custom_kg),
                    timeout=config.timeout_seconds,
                )
            )
    except TimeoutError:
        return _replace_report(
            base_report,
            skipped=False,
            skip_reason="TIMEOUT",
            graph_write_attempted=True,
            cleanup_passed=_cleanup_path(config.working_dir),
            elapsed_ms=_elapsed_ms(started),
            isolated_graph_env_count=isolated_graph_env_count,
            issues=[_issue("TIMEOUT", "Real custom_kg smoke timed out.")],
            recommended_next_step="FIX_CUSTOM_KG_TIMEOUT",
        )
    except Exception as exc:
        issue_code = (
            "REAL_GRAPH_STORAGE_ISOLATION_FAILED"
            if "neo4j" in str(exc).lower()
            else "REAL_CUSTOM_KG_SMOKE_FAILED"
        )
        return _replace_report(
            base_report,
            skipped=issue_code == "REAL_GRAPH_STORAGE_ISOLATION_FAILED",
            skip_reason=issue_code,
            graph_write_attempted=True,
            cleanup_passed=_cleanup_path(config.working_dir),
            elapsed_ms=_elapsed_ms(started),
            isolated_graph_env_count=isolated_graph_env_count,
            issues=[
                _issue(
                    issue_code,
                    f"{type(exc).__name__}: {exc}",
                )
            ],
            recommended_next_step="FIX_GRAPH_STORAGE_CONFIG",
        )

    return _replace_report(
        base_report,
        skipped=False,
        skip_reason=None,
        working_dir=result["working_dir"],
        ainsert_custom_kg_called=True,
        graph_write_attempted=True,
        graph_write_succeeded=True,
        neo4j_connected=False,
        fake_embedding_used=True,
        fake_llm_used=True,
        cleanup_passed=result["cleanup_passed"],
        elapsed_ms=_elapsed_ms(started),
        isolated_graph_env_count=isolated_graph_env_count,
        recommended_next_step=(
            "TRY_FX_MINI_GRAPH_SMOKE"
            if result["cleanup_passed"]
            else "FIX_GRAPH_ROLLBACK_BEFORE_NEXT_STEP"
        ),
    )


async def _run_real_custom_kg_smoke_async(
    config: RealCustomKgSmokeConfig,
    custom_kg: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    working_dir = config.working_dir
    if working_dir is None:
        temp_dir_value = ""
        with tempfile.TemporaryDirectory(prefix="lightrag_dsl_graph_smoke_") as temp_dir:
            temp_dir_value = temp_dir
            result = await _run_real_custom_kg_smoke_in_working_dir(
                config,
                custom_kg,
                temp_dir,
            )
        result["cleanup_passed"] = not Path(temp_dir_value).exists()
        return result

    result = await _run_real_custom_kg_smoke_in_working_dir(
        config,
        custom_kg,
        working_dir,
    )
    if config.cleanup_after_run:
        result["cleanup_passed"] = _cleanup_path(working_dir)
    return result


async def _run_real_custom_kg_smoke_in_working_dir(
    config: RealCustomKgSmokeConfig,
    custom_kg: dict[str, list[dict[str, Any]]],
    working_dir: str,
) -> dict[str, Any]:
    if not _is_safe_working_dir(working_dir):
        raise RuntimeError(f"Unsafe working_dir: {working_dir}")

    rag = None
    try:
        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc, Tokenizer

        rag = LightRAG(
            working_dir=working_dir,
            workspace=config.workspace,
            kv_storage=_LOCAL_STORAGE_TYPES["kv_storage"],
            vector_storage=_LOCAL_STORAGE_TYPES["vector_storage"],
            graph_storage=config.local_graph_storage,
            doc_status_storage=_LOCAL_STORAGE_TYPES["doc_status_storage"],
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
        await rag.ainsert_custom_kg(custom_kg, full_doc_id=config.namespace)
    finally:
        if rag is not None:
            await rag.finalize_storages()

    return {"working_dir": working_dir, "cleanup_passed": True}


async def _fake_embedding(
    texts: list[str],
    *,
    context: str | None = None,
) -> np.ndarray:
    vectors = []
    for text in texts:
        digest = hashlib.sha256(f"{context or ''}:{text}".encode("utf-8")).digest()
        values = [((digest[index] / 255.0) * 2.0) - 1.0 for index in range(8)]
        vectors.append(values)
    return np.array(vectors, dtype=np.float32)


async def _fake_llm(*args, **kwargs) -> str:
    return "DSL test fake LLM response."


class _SimpleTokenizer:
    def encode(self, content: str) -> list[int]:
        return list(range(len(str(content).split())))

    def decode(self, tokens: list[int]) -> str:
        return " ".join(f"tok{token}" for token in tokens)


def serialize_real_graph_smoke_report(report: RealGraphSmokeReport) -> dict[str, Any]:
    return asdict(report)


def _smoke_metadata(content: str) -> dict[str, Any]:
    return {
        "documentId": "DSL_TEST_REAL_CUSTOM_KG_SMOKE",
        "sourceUsId": "DSL_TEST_US_001",
        "textUnitId": SMOKE_SOURCE_ID,
        "sourceSpan": {"start": 0, "end": len(content)},
        "textHash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "evidenceText": content,
        "featureKey": "TestFeature",
        "domainCode": "DSL_TEST",
        "sectionType": "smoke",
        "knowledgeStatus": "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": "AUTO_ACCEPT_FOR_REPORT",
        "confidenceScore": 1.0,
        "ruleVersion": "dsl-test-v1",
        "latestFlag": True,
        "versionStatus": "latest",
        "supersedes": [],
        "originalTerm": None,
        "canonicalTerm": None,
        "candidateId": "dsl-test-smoke",
        "extractionRunId": "dsl-test-real-custom-kg-smoke",
        "pilotReportId": "dsl-test-real-custom-kg-smoke",
    }


def _base_report(
    config: RealCustomKgSmokeConfig,
    *,
    custom_kg: dict[str, list[dict[str, Any]]],
    sidecar_record_count: int,
    sidecar_alignment_passed: bool,
    started: float,
) -> RealGraphSmokeReport:
    return RealGraphSmokeReport(
        enabled=config.enabled,
        skipped=True,
        skip_reason=None,
        working_dir=config.working_dir,
        workspace=config.workspace,
        graph_storage_type=config.graph_storage_type,
        custom_kg_chunk_count=len(custom_kg.get("chunks", [])),
        custom_kg_entity_count=len(custom_kg.get("entities", [])),
        custom_kg_relationship_count=len(custom_kg.get("relationships", [])),
        sidecar_record_count=sidecar_record_count,
        sidecar_alignment_passed=sidecar_alignment_passed,
        ainsert_custom_kg_called=False,
        graph_write_attempted=False,
        graph_write_succeeded=False,
        neo4j_connected=False,
        production_namespace_blocked=False,
        fake_embedding_used=config.use_fake_embedding,
        fake_llm_used=config.use_fake_llm,
        cleanup_passed=True,
        timeout_seconds=config.timeout_seconds,
        elapsed_ms=_elapsed_ms(started),
        isolated_graph_env_count=0,
        issues=[],
        recommended_next_step="",
    )


def _replace_report(report: RealGraphSmokeReport, **changes: Any) -> RealGraphSmokeReport:
    data = asdict(report)
    data.update(changes)
    data["elapsed_ms"] = max(data.get("elapsed_ms", 0), 0)
    return RealGraphSmokeReport(**data)


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": message}


def _is_safe_namespace(value: str) -> bool:
    lowered = value.lower()
    return (
        ("test" in lowered or "dsl_test" in lowered)
        and lowered not in {"default", "main", "prod", "production"}
    )


def _is_safe_working_dir(working_dir: str) -> bool:
    path = str(Path(working_dir)).lower()
    return (
        ("/tmp" in path or "/private/tmp" in path or "var/folders" in path)
        and ("dsl_test" in path or "lightrag_dsl_graph_smoke" in path)
    )


def _neo4j_config_present(config: RealCustomKgSmokeConfig) -> bool:
    if config.graph_storage_type == "Neo4JStorage":
        return True
    if config.local_graph_storage == "Neo4JStorage":
        return True
    graph_storage_env = os.getenv("LIGHTRAG_GRAPH_STORAGE") or os.getenv("GRAPH_STORAGE")
    if graph_storage_env == "Neo4JStorage":
        return True
    return any(os.getenv(name) for name in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"))


def _cleanup_path(working_dir: str | None) -> bool:
    if not working_dir:
        return True
    path = Path(working_dir)
    if path.exists() and _is_safe_working_dir(str(path)):
        shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


__all__ = [
    "ENABLE_REAL_SMOKE_ENV",
    "GraphRemoteEnvIsolation",
    "REMOTE_GRAPH_ENV_VARS",
    "RealCustomKgSmokeConfig",
    "RealGraphSmokeReport",
    "build_minimal_real_smoke_custom_kg_input",
    "build_minimal_real_smoke_payload",
    "run_real_custom_kg_smoke",
    "serialize_real_graph_smoke_report",
    "without_graph_remote_env",
]
