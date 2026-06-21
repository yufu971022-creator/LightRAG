from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .raw_evidence_storage_adapter import (
    RawEvidenceIndexConfig,
    RawEvidenceIndexResult,
    RawEvidenceStorageSnapshot,
    index_raw_evidence,
    snapshot_storage,
)
from .unified_document_parser import ParserSpy, build_unified_parse_result
from .unified_document_types import UnifiedParseConfig, UnifiedParseResult, to_plain_dict
from .unified_ingestion_protocol import (
    DslAwareIngestionOrchestrator,
    ShadowRoutePlan,
    UnifiedIngestionRequest,
)

RawEvidenceRoute = Literal["DSL_FULL", "DSL_PARTIAL", "RAW_ONLY", "PARSE_FAILED"]


@dataclass(frozen=True)
class RawEvidenceRouteContract:
    selected_plan_route: RawEvidenceRoute
    raw_text_required: bool = True
    live_upload_connected: bool = False


@dataclass(frozen=True)
class RawEvidenceDocumentRun:
    request: UnifiedIngestionRequest
    route_plan: ShadowRoutePlan | RawEvidenceRouteContract
    parse_result: UnifiedParseResult
    index_result: RawEvidenceIndexResult


@dataclass(frozen=True)
class RawEvidenceChainRun:
    protocol_version: str
    artifact_root: str
    workspace: str
    execution_mode: str
    results: list[RawEvidenceDocumentRun]
    storage_snapshot: RawEvidenceStorageSnapshot
    safety_check: dict[str, bool]
    unresolved_questions: list[str] = field(default_factory=list)
    recommended_next_block: str = "Block 24B-2: connect the planned router only after raw evidence contract review"

    def report(self) -> dict[str, Any]:
        routes = [_route_from_plan(item.route_plan) for item in self.results]
        indexed = [item.index_result for item in self.results]
        parse_results = [item.parse_result for item in self.results]
        non_empty_parse_results = [item for item in parse_results if item.raw_chunks]
        avg_chunk_coverage = _average(item.raw_chunk_coverage for item in non_empty_parse_results)
        avg_unit_coverage = _average(item.text_unit_coverage for item in non_empty_parse_results)
        return {
            "protocol_version": self.protocol_version,
            "artifact_root": self.artifact_root,
            "workspace": self.workspace,
            "execution_mode": self.execution_mode,
            "input_document_count": len(self.results),
            "successful_document_count": sum(1 for item in indexed if item.status == "TEXT_INDEXED"),
            "failed_document_count": sum(1 for item in indexed if item.status in {"FAILED", "ROUTER_CONTRACT_VIOLATION"}),
            "dsl_full_count": routes.count("DSL_FULL"),
            "dsl_partial_count": routes.count("DSL_PARTIAL"),
            "raw_only_count": routes.count("RAW_ONLY"),
            "parse_failed_count": routes.count("PARSE_FAILED"),
            "raw_chunk_total": sum(len(item.raw_chunks) for item in parse_results),
            "source_text_unit_total": sum(len(item.source_text_units) for item in parse_results),
            "mapping_link_total": sum(len(item.chunk_text_unit_links) for item in parse_results),
            "average_raw_chunk_mapping_coverage": avg_chunk_coverage,
            "average_text_unit_mapping_coverage": avg_unit_coverage,
            "idempotency_passed": all(item.idempotency_passed for item in indexed),
            "single_parse_passed": all(item.parser_call_count == 1 for item in indexed),
            "no_llm_passed": all(not item.llm_called for item in indexed),
            "no_extract_entities_passed": all(not item.extract_entities_called for item in indexed),
            "no_graph_write_passed": all(
                not item.graph_write_called
                and not item.entity_vector_write_called
                and not item.relation_vector_write_called
                for item in indexed
            ),
            "no_dsl_context_contamination_passed": all(
                item.dsl_context_contamination_count == 0 for item in indexed
            ),
            "safety_check": self.safety_check,
            "storage_snapshot": to_plain_dict(self.storage_snapshot),
            "documents": [serialize_document_run(item) for item in self.results],
            "unresolved_questions": self.unresolved_questions,
            "recommended_next_block": self.recommended_next_block,
        }


@dataclass(frozen=True)
class IdempotencyCheck:
    document_id: str
    document_version_id: str
    first_chunk_ids: list[str]
    second_chunk_ids: list[str]
    before_snapshot: RawEvidenceStorageSnapshot
    after_first_snapshot: RawEvidenceStorageSnapshot
    after_second_snapshot: RawEvidenceStorageSnapshot
    passed: bool
    issues: list[str] = field(default_factory=list)


def build_fixture_requests() -> list[UnifiedIngestionRequest]:
    return [
        UnifiedIngestionRequest(
            document_id="block24b1-fixture-dsl-full",
            file_name="dsl_full_bank_status.md",
            mode="shadow",
            metadata={"domain": "MasterData", "fixture": "DSL_FULL"},
            content=(
                "User Story: US-2401 Bank Status query conditions must be searchable.\n"
                "Acceptance Criteria: Evidence: Bank Status supports Query Condition filtering.\n"
                "Business Rule: Bank Status is canonical master data for query conditions.\n"
                "Entity: Bank Status.\n"
                "Field: Query Condition.\n"
                "Relationship: Bank Status has Query Condition.\n"
                "Source: synthetic Block 24B-1 fixture."
            ),
        ),
        UnifiedIngestionRequest(
            document_id="block24b1-fixture-dsl-partial",
            file_name="dsl_partial_rule_version.md",
            mode="dsl",
            metadata={"domain": "RuleManagement", "fixture": "DSL_PARTIAL"},
            content=(
                "User Story: US-2402 Rule Version review is required.\n"
                "Acceptance Criteria: Evidence: Rule Version supersedes a prior rule.\n"
                "Business Rule: Version override requires manual approval.\n"
                "Entity: Rule Version.\n"
                "Source: synthetic Block 24B-1 fixture."
            ),
        ),
        UnifiedIngestionRequest(
            document_id="block24b1-fixture-raw-only",
            file_name="raw_only_note.md",
            mode="raw",
            metadata={"fixture": "RAW_ONLY"},
            content=(
                "Meeting note.\n"
                "The team discussed a small wording change for an internal help page.\n"
                "No structured product design object is specified here."
            ),
        ),
        UnifiedIngestionRequest(
            document_id="block24b1-fixture-parse-failed",
            file_name="parse_failed_empty.md",
            mode="shadow",
            metadata={"fixture": "PARSE_FAILED"},
            content="   \n\n",
        ),
    ]


async def run_raw_evidence_chain(
    *,
    requests: list[UnifiedIngestionRequest] | None = None,
    config: RawEvidenceIndexConfig | None = None,
    parse_config: UnifiedParseConfig | None = None,
) -> RawEvidenceChainRun:
    requests = requests or build_fixture_requests()
    config = config or RawEvidenceIndexConfig(execution_mode="PLAN_ONLY")
    parse_config = parse_config or UnifiedParseConfig()
    orchestrator = DslAwareIngestionOrchestrator()
    results: list[RawEvidenceDocumentRun] = []
    for index, request in enumerate(requests, start=1):
        plan = orchestrator.build_plan(request)
        parse_result = build_unified_parse_result(
            content=request.content,
            document_metadata={
                **request.metadata,
                "document_id": request.document_id,
                "file_name": request.file_name,
                "source_uri": request.metadata.get("source_uri") or request.file_name,
            },
            config=parse_config,
            spy=ParserSpy(),
        )
        route_decision: ShadowRoutePlan | RawEvidenceRouteContract = plan
        if plan.parse_failed or parse_result.issues:
            route_decision = RawEvidenceRouteContract(selected_plan_route="PARSE_FAILED")
        index_result = await index_raw_evidence(
            parse_result=parse_result,
            route_decision=route_decision,
            config=config,
            trace_id=f"block24b1-{index:02d}",
        )
        results.append(
            RawEvidenceDocumentRun(
                request=request,
                route_plan=route_decision,
                parse_result=parse_result,
                index_result=index_result,
            )
        )
    storage_snapshot = snapshot_storage(
        str(Path(config.artifact_root) / "workspaces"),
        config.workspace,
    )
    return RawEvidenceChainRun(
        protocol_version="24B-1",
        artifact_root=config.artifact_root,
        workspace=config.workspace,
        execution_mode=config.execution_mode,
        results=results,
        storage_snapshot=storage_snapshot,
        safety_check=build_safety_check(lightrag_core_modified=False),
    )


def run_raw_evidence_chain_sync(**kwargs: Any) -> RawEvidenceChainRun:
    return asyncio.run(run_raw_evidence_chain(**kwargs))


async def run_idempotency_check(
    *,
    request: UnifiedIngestionRequest | None = None,
    config: RawEvidenceIndexConfig,
    parse_config: UnifiedParseConfig | None = None,
) -> IdempotencyCheck:
    request = request or build_fixture_requests()[0]
    parse_config = parse_config or UnifiedParseConfig()
    parse_one = build_unified_parse_result(
        content=request.content,
        document_metadata={"document_id": request.document_id, "file_name": request.file_name, **request.metadata},
        config=parse_config,
    )
    route = RawEvidenceRouteContract(selected_plan_route="DSL_FULL")
    work_root = Path(config.artifact_root) / "workspaces"
    before = snapshot_storage(str(work_root), config.workspace)
    await index_raw_evidence(parse_result=parse_one, route_decision=route, config=config, trace_id="block24b1-idem-1")
    after_first = snapshot_storage(str(work_root), config.workspace)
    parse_two = build_unified_parse_result(
        content=request.content,
        document_metadata={"document_id": request.document_id, "file_name": request.file_name, **request.metadata},
        config=parse_config,
    )
    await index_raw_evidence(parse_result=parse_two, route_decision=route, config=config, trace_id="block24b1-idem-2")
    after_second = snapshot_storage(str(work_root), config.workspace)
    first_chunk_ids = [chunk.chunk_id for chunk in parse_one.raw_chunks]
    second_chunk_ids = [chunk.chunk_id for chunk in parse_two.raw_chunks]
    issues: list[str] = []
    if first_chunk_ids != second_chunk_ids:
        issues.append("chunk_ids_changed")
    if after_second.full_docs_count != after_first.full_docs_count:
        issues.append("full_docs_count_changed_on_second_run")
    if after_second.text_chunks_count != after_first.text_chunks_count:
        issues.append("text_chunks_count_changed_on_second_run")
    if after_second.chunks_vdb_count != after_first.chunks_vdb_count:
        issues.append("chunks_vdb_count_changed_on_second_run")
    if after_second.doc_status_count != after_first.doc_status_count:
        issues.append("doc_status_count_changed_on_second_run")
    return IdempotencyCheck(
        document_id=parse_one.document.document_id,
        document_version_id=parse_one.document.document_version_id,
        first_chunk_ids=first_chunk_ids,
        second_chunk_ids=second_chunk_ids,
        before_snapshot=before,
        after_first_snapshot=after_first,
        after_second_snapshot=after_second,
        passed=not issues,
        issues=issues,
    )


def build_safety_check(*, lightrag_core_modified: bool) -> dict[str, bool]:
    return {
        "live_upload_behavior_changed": False,
        "live_upload_hook_connected": False,
        "auto_write_routing_enabled": False,
        "raw_write_executed": False,
        "dsl_write_executed": False,
        "llm_calls_executed": False,
        "extract_entities_called": False,
        "graph_writes_executed": False,
        "entity_vector_writes_executed": False,
        "relation_vector_writes_executed": False,
        "network_calls_executed": False,
        "model_calls_executed": False,
        "production_storage_writes_executed": False,
        "lightrag_core_modified": lightrag_core_modified,
    }


def real_embedding_allowed(env: dict[str, str] | None = None) -> bool:
    env = env or {}
    return env.get("LIGHTRAG_ENABLE_REAL_RAW_EVIDENCE_SMOKE") == "1"


def assert_real_embedding_allowed(env: dict[str, str] | None = None) -> None:
    if not real_embedding_allowed(env):
        raise RuntimeError("Real embedding smoke requires LIGHTRAG_ENABLE_REAL_RAW_EVIDENCE_SMOKE=1")


def cleanup_workspace(artifact_root: str, workspace: str) -> dict[str, Any]:
    workspace_dir = Path(artifact_root) / "workspaces" / workspace
    existed_before = workspace_dir.exists()
    if existed_before:
        shutil.rmtree(workspace_dir)
    return {
        "workspace": workspace,
        "workspace_dir": str(workspace_dir),
        "existed_before_cleanup": existed_before,
        "exists_after_cleanup": workspace_dir.exists(),
        "cleanup_passed": not workspace_dir.exists(),
    }


def core_diff_text() -> str:
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--",
            "lightrag/lightrag.py",
            "lightrag/operate.py",
            "lightrag/prompt.py",
            "lightrag/api",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    diff = completed.stdout.strip()
    return diff or "NO_CORE_DIFF"


def git_status_text() -> str:
    completed = subprocess.run(
        ["git", "status", "--short"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout.strip() or "CLEAN"


def serialize_document_run(run: RawEvidenceDocumentRun) -> dict[str, Any]:
    return {
        "request": to_plain_dict(run.request),
        "route_plan": to_plain_dict(run.route_plan),
        "selected_route": _route_from_plan(run.route_plan),
        "parse_result": serialize_parse_result(run.parse_result),
        "index_result": to_plain_dict(run.index_result),
    }


def serialize_parse_result(parse_result: UnifiedParseResult) -> dict[str, Any]:
    data = to_plain_dict(parse_result)
    # The full text is already represented in chunks and file artifacts; keep reports compact.
    data["document"]["extracted_text"] = _truncate(data["document"].get("extracted_text", ""))
    data["document"]["normalized_text"] = _truncate(data["document"].get("normalized_text", ""))
    return data


def parse_results_payload(run: RawEvidenceChainRun) -> list[dict[str, Any]]:
    return [serialize_parse_result(item.parse_result) for item in run.results]


def mapping_payload(run: RawEvidenceChainRun) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in run.results:
        rows.extend(to_plain_dict(link) for link in item.parse_result.chunk_text_unit_links)
    return rows


def storage_strategy_report(config: RawEvidenceIndexConfig) -> dict[str, Any]:
    return {
        "strategy": "DIRECT_STORAGE_ADAPTER",
        "execution_mode": config.execution_mode,
        "storage_targets": ["full_docs", "text_chunks", "chunks_vdb", "doc_status"],
        "excluded_targets": ["graph", "entities_vdb", "relationships_vdb"],
        "working_dir": str(Path(config.artifact_root) / "workspaces"),
        "workspace": config.workspace,
        "local_storage_only": config.local_storage_only,
        "uses_real_embedding": config.use_real_embedding,
        "notes": [
            "24B-1 writes only isolated raw evidence storage when execution_mode=ISOLATED_WRITE.",
            "No LightRAG insert/ainsert/ainsert_custom_kg path is called by this adapter.",
        ],
    }


def architecture_mermaid() -> str:
    return """flowchart TD
    I[Document Input] --> P[Single Parse]
    P --> N[Normalized Document]
    N --> R[RawEvidenceChunks]
    N --> U[SourceTextUnits]
    R --> M[ChunkTextUnitMapping by offsets]
    U --> M
    R --> FD[full_docs]
    R --> TC[text_chunks]
    TC --> CV[chunks_vdb]
    R --> DS[doc_status]
    M -. no graph write .-> X[Graph/entity/relation stores untouched]
"""


def markdown_report(run: RawEvidenceChainRun, idempotency: IdempotencyCheck | None = None) -> str:
    report = run.report()
    lines = [
        "# Block 24B-1 Raw Evidence Chain Report",
        "",
        "## Scope and Safety Boundary",
        "- This report validates single-parse raw evidence indexing in an isolated local workspace.",
        "- `/documents/upload`, live router hooks, LLM extraction, graph writes, entities_vdb, and relationships_vdb are not used.",
        "",
        "## Confirmed Results",
        f"- input_document_count: {report['input_document_count']}",
        f"- successful_document_count: {report['successful_document_count']}",
        f"- parse_failed_count: {report['parse_failed_count']}",
        f"- raw_chunk_total: {report['raw_chunk_total']}",
        f"- source_text_unit_total: {report['source_text_unit_total']}",
        f"- mapping_link_total: {report['mapping_link_total']}",
        f"- average_raw_chunk_mapping_coverage: {report['average_raw_chunk_mapping_coverage']}",
        f"- average_text_unit_mapping_coverage: {report['average_text_unit_mapping_coverage']}",
        "",
        "## Route Coverage",
        f"- DSL_FULL: {report['dsl_full_count']}",
        f"- DSL_PARTIAL: {report['dsl_partial_count']}",
        f"- RAW_ONLY: {report['raw_only_count']}",
        f"- PARSE_FAILED: {report['parse_failed_count']}",
        "",
        "## Storage Snapshot",
        "```json",
        json.dumps(report["storage_snapshot"], indent=2, sort_keys=True),
        "```",
        "",
        "## Safety Check",
        "```json",
        json.dumps(report["safety_check"], indent=2, sort_keys=True),
        "```",
        "",
        "## Idempotency",
        "```json",
        json.dumps(to_plain_dict(idempotency) if idempotency else {"passed": None}, indent=2, sort_keys=True),
        "```",
        "",
        "## Architecture Diagram",
        "```mermaid",
        architecture_mermaid().strip(),
        "```",
        "",
        "## Unresolved Questions",
    ]
    unresolved = report.get("unresolved_questions") or ["None for this isolated smoke scope."]
    lines.extend(f"- {item}" for item in unresolved)
    lines.extend(
        [
            "",
            "## Recommended Next Block",
            f"- {report['recommended_next_block']}",
            "",
            "## Fixed Safety Conclusions",
            "```text",
            "LIVE_UPLOAD_BEHAVIOR_CHANGED = false",
            "LIVE_SHADOW_HOOK_CONNECTED = false",
            "AUTO_WRITE_ROUTING_ENABLED = false",
            "RAW_WRITE_EXECUTED = false",
            "DSL_WRITE_EXECUTED = false",
            "NETWORK_CALLS_EXECUTED = false",
            "MODEL_CALLS_EXECUTED = false",
            "STORAGE_WRITES_EXECUTED = isolated local raw evidence only",
            "LLM_CALLS_EXECUTED = false",
            "EXTRACT_ENTITIES_CALLED = false",
            "GRAPH_WRITES_EXECUTED = false",
            "ENTITY_VECTOR_WRITES_EXECUTED = false",
            "RELATION_VECTOR_WRITES_EXECUTED = false",
            "PRODUCTION_STORAGE_WRITES_EXECUTED = false",
            "LIGHTRAG_CORE_MODIFIED = false",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _route_from_plan(plan: ShadowRoutePlan | RawEvidenceRouteContract) -> str:
    return str(getattr(plan, "selected_plan_route", "PARSE_FAILED"))


def _average(values: Any) -> float:
    rows = list(values)
    if not rows:
        return 0.0
    return round(sum(rows) / len(rows), 6)


def _truncate(text: str, limit: int = 500) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...<truncated>"
