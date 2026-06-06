from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar

from .confirmed_graph_custom_kg import (
    build_confirmed_custom_kg_input_report,
    build_confirmed_graph_sidecar_records,
    validate_confirmed_sidecar_alignment,
)
from .graph_write_governance import validate_graph_write_plan
from .kg_metadata_sidecar import KgMetadataSidecarRecord, KgMetadataSidecarStore
from .kg_real_graph_smoke import (
    SMOKE_GRAPH_STORAGE,
    _SimpleTokenizer,
    _fake_embedding,
    _fake_llm,
    without_graph_remote_env,
)
from .promotion_gate import build_lc_promotion_plan_example
from .promotion_types import ConfirmedGraphWritePlan, TARGET_TEST_GRAPH


ENABLE_CONFIRMED_GRAPH_WRITE_DRY_RUN_ENV = (
    "LIGHTRAG_ENABLE_DSL_AWARE_CONFIRMED_GRAPH_WRITE_DRY_RUN"
)

LOCAL_STORAGE_TYPES = {
    "kv_storage": "JsonKVStorage",
    "vector_storage": "NanoVectorDBStorage",
    "graph_storage": SMOKE_GRAPH_STORAGE,
    "doc_status_storage": "JsonDocStatusStorage",
}


@dataclass
class ConfirmedGraphWriteDryRunConfig:
    __test__: ClassVar[bool] = False

    enabled: bool = False
    dry_run: bool = True
    test_namespace_only: bool = True
    target_graph_type: str = TARGET_TEST_GRAPH
    namespace: str = "dsl_test_confirmed_graph"
    workspace: str = "dsl_test_confirmed_graph"
    working_dir: str | None = None
    use_temp_working_dir: bool = True
    force_local_graph_storage: bool = True
    local_graph_storage: str = SMOKE_GRAPH_STORAGE
    graph_storage_type: str = SMOKE_GRAPH_STORAGE
    isolate_remote_graph_env: bool = True
    allow_neo4j: bool = False
    use_fake_embedding: bool = True
    use_fake_llm: bool = True
    cleanup_after_run: bool = True
    rollback_after_run: bool = True
    max_entities: int = 5
    max_relationships: int = 3
    timeout_seconds: int = 120
    manifest_type: str = "TEST_MANIFEST"
    feature_flag_name: str = "enable_dsl_aware_confirmed_graph_write_dry_run"

    @classmethod
    def from_env(cls) -> "ConfirmedGraphWriteDryRunConfig":
        return cls(enabled=os.getenv(ENABLE_CONFIRMED_GRAPH_WRITE_DRY_RUN_ENV) == "1")


@dataclass
class ConfirmedGraphWriteDryRunReport:
    __test__: ClassVar[bool] = False

    enabled: bool
    skipped: bool
    skip_reason: str | None
    plan_id: str | None
    manifest_id: str | None
    manifest_type: str
    namespace: str
    working_dir: str | None
    graph_storage_type: str
    custom_kg_chunk_count: int
    custom_kg_entity_count: int
    custom_kg_relationship_count: int
    sidecar_record_count: int
    sidecar_alignment_passed: bool
    governance_passed: bool
    ainsert_custom_kg_called: bool
    graph_write_attempted: bool
    graph_write_succeeded: bool
    neo4j_connected: bool
    production_write: bool
    formal_graph_written: bool
    test_only: bool
    confirmed_entity_written_count: int
    confirmed_relationship_written_count: int
    review_required_written_count: int
    info_only_written_count: int
    version_review_required_written_count: int
    missing_evidence_written_count: int
    invalid_relation_written_count: int
    forbidden_relation_count: int
    idempotency_key_duplicate_count: int
    rollback_plan_present: bool
    rollback_executed: bool
    rollback_passed: bool
    cleanup_passed: bool
    audit_event_count: int
    fake_embedding_used: bool
    fake_llm_used: bool
    elapsed_ms: int
    issues: list[dict[str, Any]] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommended_next_step: str = ""


def run_confirmed_graph_write_dry_run(
    *,
    plan: ConfirmedGraphWritePlan | None = None,
    config: ConfirmedGraphWriteDryRunConfig | None = None,
) -> ConfirmedGraphWriteDryRunReport:
    config = config or ConfirmedGraphWriteDryRunConfig.from_env()
    started = time.monotonic()
    plan = plan or build_lc_promotion_plan_example(dry_run=True)
    namespace = plan.target_namespace or config.namespace
    custom_build = build_confirmed_custom_kg_input_report(
        plan,
        max_entities=config.max_entities,
        max_relationships=config.max_relationships,
    )
    custom_kg = custom_build.custom_kg_input
    sidecar_records = build_confirmed_graph_sidecar_records(
        plan,
        custom_kg,
        namespace=namespace,
    )
    alignment = validate_confirmed_sidecar_alignment(custom_kg, sidecar_records)
    governance = validate_graph_write_plan(plan)
    request_issues = validate_confirmed_graph_write_request(
        plan,
        custom_kg,
        sidecar_records,
        config,
    )
    base_report = _base_report(
        config,
        plan=plan,
        custom_kg=custom_kg,
        sidecar_records=sidecar_records,
        sidecar_alignment_passed=alignment.pass_status == "PASS",
        governance_passed=governance.pass_status == "PASS",
        started=started,
        namespace=namespace,
        issues=[*custom_build.issues, *request_issues],
    )

    if not config.enabled:
        return replace(
            base_report,
            skipped=True,
            skip_reason="Feature flag enable_dsl_aware_confirmed_graph_write_dry_run is disabled.",
            recommended_next_step="ENABLE_CONFIRMED_GRAPH_WRITE_DRY_RUN",
            elapsed_ms=_elapsed_ms(started),
        )
    if not custom_kg["entities"] and not custom_kg["relationships"]:
        return replace(
            base_report,
            skipped=True,
            skip_reason="NO_CONFIRMED_OBJECTS_TO_WRITE",
            recommended_next_step="COLLECT_REVIEWER_MANIFEST",
            elapsed_ms=_elapsed_ms(started),
        )
    if governance.pass_status != "PASS" or request_issues:
        return replace(
            base_report,
            skipped=True,
            skip_reason=(request_issues[0]["code"] if request_issues else "GOVERNANCE_FAIL"),
            recommended_next_step=(
                "FIX_CONFIRMED_SIDECAR_ALIGNMENT"
                if alignment.pass_status != "PASS"
                else "FIX_GRAPH_WRITE_GOVERNANCE"
            ),
            elapsed_ms=_elapsed_ms(started),
        )
    if not config.force_local_graph_storage or config.local_graph_storage != SMOKE_GRAPH_STORAGE:
        return replace(
            base_report,
            skipped=True,
            skip_reason="REAL_GRAPH_STORAGE_UNSUPPORTED",
            issues=[
                *base_report.issues,
                _issue("REAL_GRAPH_STORAGE_UNSUPPORTED", "Only local NetworkXStorage is supported."),
            ],
            recommended_next_step="FIX_GRAPH_WRITE_GOVERNANCE",
            elapsed_ms=_elapsed_ms(started),
        )
    if not config.use_fake_embedding or not config.use_fake_llm:
        return replace(
            base_report,
            skipped=True,
            skip_reason="FAKE_MODEL_REQUIRED",
            issues=[
                *base_report.issues,
                _issue("FAKE_MODEL_REQUIRED", "Confirmed dry-run must use fake embedding and fake LLM."),
            ],
            recommended_next_step="FIX_GRAPH_WRITE_GOVERNANCE",
            elapsed_ms=_elapsed_ms(started),
        )
    if not config.allow_neo4j and not config.isolate_remote_graph_env and _neo4j_config_present(config):
        return replace(
            base_report,
            skipped=True,
            skip_reason="NEO4J_BLOCKED",
            neo4j_connected=False,
            issues=[
                *base_report.issues,
                _issue("NEO4J_BLOCKED", "Neo4j config is present but allow_neo4j is false."),
            ],
            recommended_next_step="DO_NOT_WRITE_GRAPH",
            elapsed_ms=_elapsed_ms(started),
        )
    sidecar_store = KgMetadataSidecarStore()
    sidecar_store.upsert_records(sidecar_records)

    try:
        if config.isolate_remote_graph_env:
            with without_graph_remote_env():
                result = asyncio.run(
                    asyncio.wait_for(
                        _run_local_confirmed_write(config, custom_kg, namespace),
                        timeout=config.timeout_seconds,
                    )
                )
        else:
            result = asyncio.run(
                asyncio.wait_for(
                    _run_local_confirmed_write(config, custom_kg, namespace),
                    timeout=config.timeout_seconds,
                )
            )
    except TimeoutError:
        return replace(
            base_report,
            skipped=False,
            skip_reason="TIMEOUT",
            graph_write_attempted=True,
            rollback_executed=config.rollback_after_run,
            rollback_passed=False,
            cleanup_passed=_cleanup_path(config.working_dir),
            issues=[*base_report.issues, _issue("TIMEOUT", "Confirmed graph write dry-run timed out.")],
            recommended_next_step="FIX_ROLLBACK_BEFORE_NEXT_STEP",
            elapsed_ms=_elapsed_ms(started),
        )
    except Exception as exc:
        issue_code = (
            "REAL_GRAPH_STORAGE_ISOLATION_FAILED"
            if "neo4j" in str(exc).lower()
            else "CONFIRMED_GRAPH_WRITE_FAILED"
        )
        return replace(
            base_report,
            skipped=issue_code == "REAL_GRAPH_STORAGE_ISOLATION_FAILED",
            skip_reason=issue_code,
            graph_write_attempted=True,
            cleanup_passed=_cleanup_path(config.working_dir),
            issues=[*base_report.issues, _issue(issue_code, f"{type(exc).__name__}: {exc}")],
            recommended_next_step="FIX_GRAPH_WRITE_GOVERNANCE",
            elapsed_ms=_elapsed_ms(started),
        )

    rollback_executed = config.rollback_after_run
    sidecar_rollback_count = sidecar_store.delete_by_namespace(namespace) if rollback_executed else 0
    rollback_passed = not rollback_executed or sidecar_rollback_count == len(sidecar_records)
    cleanup_passed = bool(result["cleanup_passed"])
    return replace(
        base_report,
        skipped=False,
        skip_reason=None,
        working_dir=result["working_dir"],
        ainsert_custom_kg_called=True,
        graph_write_attempted=True,
        graph_write_succeeded=True,
        rollback_executed=rollback_executed,
        rollback_passed=rollback_passed,
        cleanup_passed=cleanup_passed,
        recommended_next_step=(
            "PREPARE_REVIEWER_MANIFEST_INTEGRATION"
            if rollback_passed and cleanup_passed
            else "FIX_ROLLBACK_BEFORE_NEXT_STEP"
        ),
        elapsed_ms=_elapsed_ms(started),
    )


def validate_confirmed_graph_write_request(
    plan: ConfirmedGraphWritePlan,
    custom_kg_input: dict[str, list[dict[str, Any]]],
    sidecar_records: list[KgMetadataSidecarRecord],
    config: ConfirmedGraphWriteDryRunConfig,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    governance = validate_graph_write_plan(plan)
    alignment = validate_confirmed_sidecar_alignment(custom_kg_input, sidecar_records)
    if governance.pass_status != "PASS":
        issues.append(_issue("GOVERNANCE_FAIL", "Graph write governance validation failed."))
    if alignment.pass_status != "PASS":
        issues.append(_issue("CONFIRMED_SIDECAR_ALIGNMENT_FAIL", "Confirmed sidecar alignment failed."))
    if config.test_namespace_only and not _is_safe_namespace(plan.target_namespace):
        issues.append(_issue("PRODUCTION_NAMESPACE_BLOCKED", "target namespace must contain test or dsl_test."))
    if plan.production_write:
        issues.append(_issue("PRODUCTION_WRITE_BLOCKED", "production_write must be false."))
    if plan.target_graph_type != TARGET_TEST_GRAPH:
        issues.append(_issue("FORMAL_GRAPH_WRITE_FORBIDDEN", "target_graph_type must be test_graph."))
    if config.manifest_type not in {"TEST_MANIFEST", "REVIEWER_MANIFEST"}:
        issues.append(_issue("INVALID_MANIFEST_TYPE", "manifest_type must be TEST_MANIFEST or REVIEWER_MANIFEST."))
    if not plan.rollback_plan:
        issues.append(_issue("ROLLBACK_PLAN_MISSING", "rollback plan is required."))
    if not plan.audit_events:
        issues.append(_issue("AUDIT_EVENTS_MISSING", "audit events are required."))
    if _duplicate_count(plan.idempotency_keys):
        issues.append(_issue("DUPLICATE_IDEMPOTENCY_KEY", "idempotency keys must be unique."))
    if _forbidden_relation_count(custom_kg_input):
        issues.append(_issue("FORBIDDEN_RELATION_BLOCKED", "forbidden relation appears in custom_kg input."))
    written_counts = _blocked_status_counts(sidecar_records)
    for code, count in written_counts.items():
        if count:
            issues.append(_issue(code, f"{code} count: {count}"))
    return issues


async def _run_local_confirmed_write(
    config: ConfirmedGraphWriteDryRunConfig,
    custom_kg: dict[str, list[dict[str, Any]]],
    namespace: str,
) -> dict[str, Any]:
    working_dir = config.working_dir
    if working_dir is None:
        temp_dir_value = ""
        with tempfile.TemporaryDirectory(prefix="lightrag_dsl_graph_smoke_dsl_test_confirmed_") as temp_dir:
            temp_dir_value = temp_dir
            result = await _run_in_working_dir(config, custom_kg, namespace, temp_dir)
        result["cleanup_passed"] = not Path(temp_dir_value).exists()
        return result
    result = await _run_in_working_dir(config, custom_kg, namespace, working_dir)
    if config.cleanup_after_run:
        result["cleanup_passed"] = _cleanup_path(working_dir)
    return result


async def _run_in_working_dir(
    config: ConfirmedGraphWriteDryRunConfig,
    custom_kg: dict[str, list[dict[str, Any]]],
    namespace: str,
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
            workspace=namespace,
            kv_storage=LOCAL_STORAGE_TYPES["kv_storage"],
            vector_storage=LOCAL_STORAGE_TYPES["vector_storage"],
            graph_storage=config.local_graph_storage,
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
        await rag.ainsert_custom_kg(custom_kg, full_doc_id=namespace)
    finally:
        if rag is not None:
            await rag.finalize_storages()
    return {"working_dir": working_dir, "cleanup_passed": True}


def serialize_confirmed_graph_write_dry_run_report(
    report: ConfirmedGraphWriteDryRunReport,
) -> dict[str, Any]:
    return asdict(report)


def _base_report(
    config: ConfirmedGraphWriteDryRunConfig,
    *,
    plan: ConfirmedGraphWritePlan,
    custom_kg: dict[str, list[dict[str, Any]]],
    sidecar_records: list[KgMetadataSidecarRecord],
    sidecar_alignment_passed: bool,
    governance_passed: bool,
    started: float,
    namespace: str,
    issues: list[dict[str, Any]],
) -> ConfirmedGraphWriteDryRunReport:
    counts = _blocked_status_counts(sidecar_records)
    return ConfirmedGraphWriteDryRunReport(
        enabled=config.enabled,
        skipped=True,
        skip_reason=None,
        plan_id=plan.plan_id,
        manifest_id=_manifest_id(plan),
        manifest_type=config.manifest_type,
        namespace=namespace,
        working_dir=config.working_dir,
        graph_storage_type=config.graph_storage_type,
        custom_kg_chunk_count=len(custom_kg.get("chunks", [])),
        custom_kg_entity_count=len(custom_kg.get("entities", [])),
        custom_kg_relationship_count=len(custom_kg.get("relationships", [])),
        sidecar_record_count=len(sidecar_records),
        sidecar_alignment_passed=sidecar_alignment_passed,
        governance_passed=governance_passed,
        ainsert_custom_kg_called=False,
        graph_write_attempted=False,
        graph_write_succeeded=False,
        neo4j_connected=False,
        production_write=plan.production_write,
        formal_graph_written=False,
        test_only=config.manifest_type == "TEST_MANIFEST",
        confirmed_entity_written_count=len(custom_kg.get("entities", [])),
        confirmed_relationship_written_count=len(custom_kg.get("relationships", [])),
        review_required_written_count=counts["REVIEW_REQUIRED_WRITTEN"],
        info_only_written_count=counts["INFO_ONLY_WRITTEN"],
        version_review_required_written_count=counts["VERSION_REVIEW_REQUIRED_WRITTEN"],
        missing_evidence_written_count=counts["MISSING_EVIDENCE_WRITTEN"],
        invalid_relation_written_count=counts["INVALID_RELATION_WRITTEN"],
        forbidden_relation_count=_forbidden_relation_count(custom_kg),
        idempotency_key_duplicate_count=_duplicate_count(plan.idempotency_keys),
        rollback_plan_present=plan.rollback_plan is not None,
        rollback_executed=False,
        rollback_passed=False,
        cleanup_passed=True,
        audit_event_count=len(plan.audit_events),
        fake_embedding_used=config.use_fake_embedding,
        fake_llm_used=config.use_fake_llm,
        elapsed_ms=_elapsed_ms(started),
        issues=issues,
        risks=list(plan.risks),
        recommended_next_step="",
    )


def _blocked_status_counts(records: list[KgMetadataSidecarRecord]) -> dict[str, int]:
    counts = {
        "REVIEW_REQUIRED_WRITTEN": 0,
        "INFO_ONLY_WRITTEN": 0,
        "VERSION_REVIEW_REQUIRED_WRITTEN": 0,
        "MISSING_EVIDENCE_WRITTEN": 0,
        "INVALID_RELATION_WRITTEN": 0,
    }
    for record in records:
        tokens = {
            str(record.metadata.get("knowledgeStatus")),
            str(record.metadata.get("validationStatus")),
            str(record.metadata.get("reviewDecision")),
            str(record.metadata.get("reasonCode")),
        }
        if "ReviewRequired" in tokens or "REVIEW_REQUIRED" in tokens:
            counts["REVIEW_REQUIRED_WRITTEN"] += 1
        if "InfoOnly" in tokens or "INFO_ONLY" in tokens:
            counts["INFO_ONLY_WRITTEN"] += 1
        if "VersionReviewRequired" in tokens or record.metadata.get("requiresHumanReview") is True:
            counts["VERSION_REVIEW_REQUIRED_WRITTEN"] += 1
        if "MISSING_EVIDENCE" in tokens or "MissingEvidence" in tokens:
            counts["MISSING_EVIDENCE_WRITTEN"] += 1
        if "INVALID_RELATION" in tokens or "InvalidRelation" in tokens:
            counts["INVALID_RELATION_WRITTEN"] += 1
    return counts


def _forbidden_relation_count(custom_kg: dict[str, list[dict[str, Any]]]) -> int:
    forbidden = {"has_child", "belongs_to", "references_to", "queries_from", "queries_by", "contains"}
    return sum(
        1
        for item in custom_kg.get("relationships", [])
        if str(item.get("keywords", "")).lower() in forbidden
    )


def _manifest_id(plan: ConfirmedGraphWritePlan) -> str | None:
    for event in plan.audit_events:
        manifest_id = event.metadata.get("manifestId")
        if manifest_id:
            return str(manifest_id)
    for item in [*plan.confirmed_entities, *plan.confirmed_relationships]:
        manifest_id = item.audit_metadata.get("manifestId")
        if manifest_id:
            return str(manifest_id)
    return None


def _neo4j_config_present(config: ConfirmedGraphWriteDryRunConfig) -> bool:
    if config.graph_storage_type == "Neo4JStorage" or config.local_graph_storage == "Neo4JStorage":
        return True
    graph_storage_env = os.getenv("LIGHTRAG_GRAPH_STORAGE") or os.getenv("GRAPH_STORAGE")
    if graph_storage_env == "Neo4JStorage":
        return True
    return any(os.getenv(name) for name in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"))


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


def _cleanup_path(working_dir: str | None) -> bool:
    if not working_dir:
        return True
    path = Path(working_dir)
    if path.exists() and _is_safe_working_dir(str(path)):
        shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def _duplicate_count(values: list[str]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for value in values:
        if value in seen:
            duplicates += 1
        seen.add(value)
    return duplicates


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"severity": "ERROR", "code": code, "message": message}


__all__ = [
    "ENABLE_CONFIRMED_GRAPH_WRITE_DRY_RUN_ENV",
    "ConfirmedGraphWriteDryRunConfig",
    "ConfirmedGraphWriteDryRunReport",
    "run_confirmed_graph_write_dry_run",
    "serialize_confirmed_graph_write_dry_run_report",
    "validate_confirmed_graph_write_request",
]
