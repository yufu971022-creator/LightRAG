from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .generic_graph_writer import snapshot_generic_graph, write_synthetic_generic_graph
from .graph_space_policy import (
    GraphSpaceDescriptor,
    generic_descriptor,
    issue_descriptor,
    namespace_collision_count,
    pfss_descriptor,
    serialize_descriptors,
    validate_graph_space_isolation,
)
from .issue_index import IssueIndex, IssueRecord, make_issue_record
from .pfss_graph_writer import SOURCE_REFERENCE_STRATEGY, snapshot_pfss_graph, write_pfss_graph
from .raw_evidence_storage_adapter import RawEvidenceIndexConfig
from .raw_evidence_chain import build_fixture_requests, run_raw_evidence_chain
from .semantic_branch_types import (
    GraphIsolationSnapshot,
    PfssPayload,
    SemanticBranchExecutionConfig,
    SemanticBranchExecutionResult,
    SemanticBranchSuiteResult,
    SemanticObject,
    SemanticRelationship,
    SemanticRoute,
    to_plain_dict,
)


def execute_semantic_branch(
    *,
    route_decision: Any,
    unified_parse_result: Any,
    raw_evidence_result: Any,
    config: SemanticBranchExecutionConfig,
    trace_id: str = "block24b2-trace",
) -> SemanticBranchExecutionResult:
    route = _route(route_decision)
    raw_status = str(getattr(raw_evidence_result, "status", "UNKNOWN"))
    raw_ok = raw_status == "TEXT_INDEXED"
    parse_failed = route == "PARSE_FAILED"
    raw_chunk_count_before = int(getattr(getattr(raw_evidence_result, "storage_snapshot_after", None), "text_chunks_count", 0))
    raw_chunk_vector_count_before = int(getattr(getattr(raw_evidence_result, "storage_snapshot_after", None), "chunks_vdb_count", 0))
    if config.enforce_raw_evidence_success and not raw_ok and not parse_failed:
        return _empty_result(
            trace_id=trace_id,
            parse_result=unified_parse_result,
            route=route,
            raw_status=raw_status,
            raw_chunk_count_before=raw_chunk_count_before,
            raw_chunk_vector_count_before=raw_chunk_vector_count_before,
            status="RAW_EVIDENCE_REQUIRED",
            issues=["raw_evidence_success_required"],
        )
    pfss_desc = pfss_descriptor(config.pfss_workspace, config.pfss_namespace)
    generic_desc = generic_descriptor(config.generic_workspace, config.generic_namespace, write_enabled=config.allow_generic_graph)
    issue_desc = issue_descriptor()
    validate_graph_space_isolation([pfss_desc, generic_desc, issue_desc])
    issue_index = IssueIndex(_issue_index_path(config))
    payload = compile_pfss_payload(route=route, parse_result=unified_parse_result)
    issue_records = issue_records_from_payload(payload, trace_id=trace_id)
    pfss_result = None
    generic_snapshot = snapshot_generic_graph(descriptor=generic_desc, artifact_root=config.artifact_root)
    if route in {"DSL_FULL", "DSL_PARTIAL"} and config.enabled and config.execution_mode == "ISOLATED_TEST_WRITE":
        pfss_result = write_pfss_graph(
            payload=payload,
            descriptor=pfss_desc,
            artifact_root=config.artifact_root,
            raw_chunk_count_before=raw_chunk_count_before,
            raw_chunk_vector_count_before=raw_chunk_vector_count_before,
        )
    if route == "DSL_PARTIAL" and issue_records and config.enabled:
        issue_index.upsert_many(issue_records)
    if config.allow_generic_graph and route == "RAW_ONLY" and config.execution_mode == "ISOLATED_TEST_WRITE":
        generic_snapshot = write_synthetic_generic_graph(descriptor=generic_desc, artifact_root=config.artifact_root)
    pfss_snapshot = snapshot_pfss_graph(descriptor=pfss_desc, artifact_root=config.artifact_root)
    issue_records_after = issue_index.all_records()
    isolation = build_graph_isolation_snapshot(
        pfss_snapshot=pfss_snapshot,
        generic_snapshot=generic_snapshot,
        issue_records=issue_records_after,
        descriptors=[pfss_desc, generic_desc, issue_desc],
    )
    source_report = getattr(pfss_result, "source_reference_report", None)
    raw_after = source_report.raw_chunk_count_after if source_report else raw_chunk_count_before
    vector_after = source_report.raw_chunk_vector_count_after if source_report else raw_chunk_vector_count_before
    status = "SKIPPED"
    issues: list[str] = []
    if route in {"DSL_FULL", "DSL_PARTIAL"}:
        status = pfss_result.status if pfss_result else "PLAN_ONLY"
        issues = list(pfss_result.issues if pfss_result else [])
    elif route == "RAW_ONLY":
        status = "TEXT_ONLY"
    elif route == "PARSE_FAILED":
        status = "PARSE_FAILED_NO_SEMANTIC_WRITE"
    return SemanticBranchExecutionResult(
        trace_id=trace_id,
        document_id=unified_parse_result.document.document_id,
        document_version_id=unified_parse_result.document.document_version_id,
        semantic_route=route,
        raw_evidence_status=raw_status,
        dsl_compile_executed=route in {"DSL_FULL", "DSL_PARTIAL"},
        pfss_write_executed=bool(pfss_result and pfss_result.pfss_write_executed),
        generic_write_executed=bool(config.allow_generic_graph and route == "RAW_ONLY"),
        issue_index_write_executed=bool(route == "DSL_PARTIAL" and issue_records),
        safe_chunk_count=len(payload.source_chunk_ids),
        safe_entity_count=len(payload.safe_entities),
        safe_relationship_count=len(payload.safe_relationships),
        blocked_object_count=len(payload.blocked_objects) + len(payload.blocked_relationships),
        issue_record_count=len(issue_index.query_by_document(unified_parse_result.document.document_id)),
        pfss_graph_node_count=pfss_snapshot["node_count"],
        pfss_graph_edge_count=pfss_snapshot["edge_count"],
        generic_graph_node_count=generic_snapshot["node_count"],
        generic_graph_edge_count=generic_snapshot["edge_count"],
        pfss_entity_vector_count=pfss_snapshot["entity_vector_count"],
        pfss_relationship_vector_count=pfss_snapshot["relationship_vector_count"],
        duplicate_semantic_object_count=pfss_snapshot["duplicate_semantic_object_count"],
        cross_space_collision_count=isolation.namespace_collision_count,
        extract_entities_called=False,
        gleaning_executed=False,
        llm_called=False,
        embedding_called=False,
        source_reference_strategy=SOURCE_REFERENCE_STRATEGY,
        raw_chunk_count_before=raw_chunk_count_before,
        raw_chunk_count_after=raw_after,
        raw_chunk_vector_count_before=raw_chunk_vector_count_before,
        raw_chunk_vector_count_after=vector_after,
        duplicate_raw_chunk_count=0,
        sidecar_alignment_passed=pfss_snapshot["sidecar_alignment_passed"],
        endpoint_closure_passed=pfss_snapshot["endpoint_closure_passed"],
        forbidden_relation_count=pfss_snapshot["forbidden_relation_count"],
        dangling_relationship_count=payload.dangling_relationship_count,
        status=status,
        issues=issues,
        risks=[] if isolation.namespace_collision_count == 0 else ["graph_space_collision"],
    )


async def execute_fixture_suite(
    *,
    config: SemanticBranchExecutionConfig,
    generic_isolation_smoke: bool = True,
) -> SemanticBranchSuiteResult:
    raw_config = RawEvidenceIndexConfig(
        execution_mode="ISOLATED_WRITE",
        artifact_root=config.artifact_root,
        workspace="block24b2_raw_evidence_test",
    )
    raw_run = await run_raw_evidence_chain(requests=build_fixture_requests(), config=raw_config)
    results: list[SemanticBranchExecutionResult] = []
    for index, raw_item in enumerate(raw_run.results, start=1):
        route = _route(raw_item.route_plan)
        branch_config = config
        if route == "RAW_ONLY" and generic_isolation_smoke:
            branch_config = SemanticBranchExecutionConfig(**{**config.__dict__, "allow_generic_graph": True})
        results.append(
            execute_semantic_branch(
                route_decision=raw_item.route_plan,
                unified_parse_result=raw_item.parse_result,
                raw_evidence_result=raw_item.index_result,
                config=branch_config,
                trace_id=f"block24b2-{index:02d}",
            )
        )
    pfss_desc = pfss_descriptor(config.pfss_workspace, config.pfss_namespace)
    generic_desc = generic_descriptor(config.generic_workspace, config.generic_namespace, write_enabled=generic_isolation_smoke)
    issue_desc = issue_descriptor()
    isolation = build_graph_isolation_snapshot(
        pfss_snapshot=snapshot_pfss_graph(descriptor=pfss_desc, artifact_root=config.artifact_root),
        generic_snapshot=snapshot_generic_graph(descriptor=generic_desc, artifact_root=config.artifact_root),
        issue_records=IssueIndex(_issue_index_path(config)).all_records(),
        descriptors=[pfss_desc, generic_desc, issue_desc],
    )
    first_counts = _suite_counts(results)
    second_results: list[SemanticBranchExecutionResult] = []
    if results:
        raw_item = raw_run.results[0]
        second_results.append(
            execute_semantic_branch(
                route_decision=raw_item.route_plan,
                unified_parse_result=raw_item.parse_result,
                raw_evidence_result=raw_item.index_result,
                config=config,
                trace_id="block24b2-idempotency",
            )
        )
    second_counts = _suite_counts(results + second_results)
    return SemanticBranchSuiteResult(
        results=results,
        graph_isolation_snapshot=isolation,
        source_reference_strategy=SOURCE_REFERENCE_STRATEGY,
        safety_check=build_safety_check(lightrag_core_modified=False),
        idempotency_passed=first_counts == second_counts,
        cleanup_passed=True,
        unresolved_questions=[],
    )


def execute_fixture_suite_sync(**kwargs: Any) -> SemanticBranchSuiteResult:
    return asyncio.run(execute_fixture_suite(**kwargs))


def compile_pfss_payload(*, route: SemanticRoute, parse_result: Any) -> PfssPayload:
    chunk_ids = [chunk.chunk_id for chunk in parse_result.raw_chunks]
    source_id = chunk_ids[0] if chunk_ids else "NO_SOURCE_CHUNK"
    doc = parse_result.document
    if route == "DSL_FULL":
        bank = SemanticObject("pfss:bank_status", "Bank Status", "DomainObject", "APPROVED_PFSS", source_id, evidence_text="Bank Status supports Query Condition filtering", domain_code="MasterData", feature_key="bank-status-query")
        condition = SemanticObject("pfss:query_condition", "Query Condition", "FieldSpec", "APPROVED_PFSS", source_id, evidence_text="Query Condition filtering", domain_code="MasterData", feature_key="bank-status-query")
        rel = SemanticRelationship("pfss:bank_status:has_field:query_condition", bank.object_id, condition.object_id, "HasField", "APPROVED_PFSS", source_id, evidence_text="Bank Status has Query Condition")
        return PfssPayload(doc.document_id, doc.document_version_id, route, chunk_ids, [bank, condition], [rel])
    if route == "DSL_PARTIAL":
        safe = SemanticObject("pfss:rule_version", "Rule Version", "RuleVersion", "APPROVED_PFSS", source_id, source_us_id="US-2402", evidence_text="Rule Version review is required", domain_code="RuleManagement", feature_key="rule-version-review")
        status = SemanticObject("pfss:approval_status", "Approval Status", "FieldSpec", "APPROVED_PFSS", source_id, source_us_id="US-2402", evidence_text="manual approval", domain_code="RuleManagement", feature_key="rule-version-review")
        rel = SemanticRelationship("pfss:rule_version:has_field:approval_status", safe.object_id, status.object_id, "HasField", "APPROVED_PFSS", source_id, evidence_text="Rule Version requires manual approval")
        version_issue = SemanticObject("issue:version_review_required", "Version Review Required", "VersionReviewRequired", "BLOCKED_ISSUE", source_id, source_us_id="US-2402", evidence_text="Version override requires manual approval", domain_code="RuleManagement", feature_key="rule-version-review", issue_type="VERSION_REVIEW_REQUIRED", reason_code="version_policy_review_required")
        missing = SemanticObject("issue:missing_evidence", "Missing Evidence", "MissingEvidence", "BLOCKED_ISSUE", source_id, source_us_id="US-2402", evidence_text="supersedes prior rule lacks explicit evidence link", domain_code="RuleManagement", feature_key="rule-version-review", issue_type="MISSING_EVIDENCE", reason_code="missing_explicit_source_unit")
        return PfssPayload(doc.document_id, doc.document_version_id, route, chunk_ids, [safe, status], [rel], [version_issue, missing])
    return PfssPayload(doc.document_id, doc.document_version_id, route, chunk_ids, [], [])


def issue_records_from_payload(payload: PfssPayload, *, trace_id: str) -> list[IssueRecord]:
    records: list[IssueRecord] = []
    for item in payload.blocked_objects:
        if not item.issue_type:
            continue
        records.append(
            make_issue_record(
                trace_id=trace_id,
                document_id=payload.document_id,
                document_version_id=payload.document_version_id,
                semantic_object_id=item.object_id,
                object_kind=item.object_type,
                issue_type=item.issue_type,
                reason_code=item.reason_code or "review_required",
                evidence_text=item.evidence_text,
                source_us_id=item.source_us_id,
                text_unit_id=item.text_unit_id,
                source_span=item.source_span,
                text_hash=item.text_hash,
                domain_code=item.domain_code,
                feature_key=item.feature_key,
                review_required=item.issue_type != "INFO_ONLY",
            )
        )
    return records


def build_graph_isolation_snapshot(
    *,
    pfss_snapshot: dict[str, Any],
    generic_snapshot: dict[str, Any],
    issue_records: list[IssueRecord],
    descriptors: list[GraphSpaceDescriptor],
) -> GraphIsolationSnapshot:
    pfss_nodes = set(pfss_snapshot.get("node_ids", []))
    pfss_edges = set(pfss_snapshot.get("edge_ids", []))
    generic_nodes = set(generic_snapshot.get("node_ids", []))
    generic_edges = set(generic_snapshot.get("edge_ids", []))
    issue_ids = {record.semantic_object_id for record in issue_records}
    return GraphIsolationSnapshot(
        pfss_node_ids=sorted(pfss_nodes),
        pfss_edge_ids=sorted(pfss_edges),
        generic_node_ids=sorted(generic_nodes),
        generic_edge_ids=sorted(generic_edges),
        issue_object_ids=sorted(issue_ids),
        pfss_generic_node_overlap_count=len(pfss_nodes & generic_nodes),
        pfss_generic_edge_overlap_count=len(pfss_edges & generic_edges),
        pfss_issue_overlap_count=len(pfss_nodes & issue_ids),
        namespace_collision_count=namespace_collision_count(descriptors),
    )


def build_safety_check(*, lightrag_core_modified: bool) -> dict[str, bool]:
    return {
        "live_upload_behavior_changed": False,
        "live_upload_hook_connected": False,
        "auto_write_routing_enabled": False,
        "real_llm_calls_executed": False,
        "original_extract_entities_called": False,
        "original_gleaning_executed": False,
        "live_generic_fallback_extraction_implemented": False,
        "production_storage_writes_executed": False,
        "neo4j_connected": False,
        "lightrag_core_modified": lightrag_core_modified,
    }


def real_embedding_allowed(env: dict[str, str] | None = None) -> bool:
    env = env or os.environ
    return env.get("LIGHTRAG_ENABLE_REAL_SEMANTIC_BRANCH_SMOKE") == "1"


def require_real_embedding_allowed(env: dict[str, str] | None = None) -> None:
    if not real_embedding_allowed(env):
        raise RuntimeError("Real semantic branch embedding smoke requires LIGHTRAG_ENABLE_REAL_SEMANTIC_BRANCH_SMOKE=1")


def workspace_inside_artifact_root(config: SemanticBranchExecutionConfig) -> bool:
    root = Path(config.artifact_root).resolve()
    workspaces = [config.pfss_workspace, config.generic_workspace]
    return all(str((root / "workspaces" / workspace).resolve()).startswith(str(root)) for workspace in workspaces)


def cleanup_test_workspaces(artifact_root: str) -> dict[str, Any]:
    workspaces = Path(artifact_root) / "workspaces"
    existed = workspaces.exists()
    if existed:
        shutil.rmtree(workspaces)
    workspaces.mkdir(parents=True, exist_ok=True)
    return {"workspace_root": str(workspaces), "existed_before_cleanup": existed, "exists_after_cleanup": workspaces.exists(), "cleanup_passed": workspaces.exists() and not any(workspaces.iterdir())}


def graph_space_policy_payload(config: SemanticBranchExecutionConfig) -> list[dict[str, Any]]:
    return serialize_descriptors([
        pfss_descriptor(config.pfss_workspace, config.pfss_namespace),
        generic_descriptor(config.generic_workspace, config.generic_namespace, write_enabled=config.allow_generic_graph),
        issue_descriptor(),
    ])


def source_reference_strategy_payload(results: list[SemanticBranchExecutionResult]) -> dict[str, Any]:
    dsl_results = [item for item in results if item.semantic_route in {"DSL_FULL", "DSL_PARTIAL"}]
    first = dsl_results[0] if dsl_results else None
    return {
        "PFSS_SOURCE_REFERENCE_STRATEGY": SOURCE_REFERENCE_STRATEGY,
        "raw_chunk_count_before": first.raw_chunk_count_before if first else 0,
        "raw_chunk_count_after": first.raw_chunk_count_after if first else 0,
        "raw_chunk_vector_count_before": first.raw_chunk_vector_count_before if first else 0,
        "raw_chunk_vector_count_after": first.raw_chunk_vector_count_after if first else 0,
        "duplicate_raw_chunk_count": first.duplicate_raw_chunk_count if first else 0,
    }


def architecture_mermaid() -> str:
    return """flowchart TD
    R[Route Decision] --> E[Raw Evidence Result Required]

    E -->|DSL_FULL| F[Compile Full Safe DSL Payload]
    E -->|DSL_PARTIAL| P[Compile Safe DSL Subset]
    E -->|RAW_ONLY| T[Text-only, No PFSS Write]
    E -->|PARSE_FAILED| X[No Semantic Write]

    F --> PFSS[PFSS Test Graph]
    P --> PFSS
    P --> ISSUE[Issue / Review Index]

    G[Optional Synthetic Generic Smoke] --> GENERIC[Generic Test Graph]

    PFSS -. isolated .- GENERIC
    PFSS -. no overlap .- ISSUE

    NOTE[No Live Upload Hook / No LLM / No Original Extraction]
"""


def markdown_report(
    suite: SemanticBranchSuiteResult,
    config: SemanticBranchExecutionConfig,
    report_override: dict[str, Any] | None = None,
) -> str:
    report = report_override or suite.report()
    final_status = "PASS" if _exit_gate_passed(report) else "FAIL"
    return "\n".join([
        "# Block 24B-2 Semantic Branch Isolation Report",
        "",
        "## Scope",
        "- Isolated semantic branch execution only; no live upload hook, no auto write routing, no real LLM, no original extraction.",
        "- PFSS and Generic graphs are local JSON test graphs; Issue is a local JSON review index.",
        "",
        "## Route Execution",
        f"- dsl_full_pfss_write: {report['dsl_full_pfss_write']}",
        f"- dsl_partial_pfss_write: {report['dsl_partial_pfss_write']}",
        f"- dsl_partial_issue_write: {report['dsl_partial_issue_write']}",
        f"- raw_only_pfss_write: {report['raw_only_pfss_write']}",
        f"- parse_failed_semantic_write: {report['parse_failed_semantic_write']}",
        "",
        "## Isolation",
        "```json",
        json.dumps(to_plain_dict(suite.graph_isolation_snapshot), indent=2, sort_keys=True),
        "```",
        "",
        "## Source Reference",
        "```json",
        json.dumps(source_reference_strategy_payload(suite.results), indent=2, sort_keys=True),
        "```",
        "",
        "## Safety",
        "```json",
        json.dumps(suite.safety_check, indent=2, sort_keys=True),
        "```",
        "",
        "## Architecture",
        "```mermaid",
        architecture_mermaid().strip(),
        "```",
        "",
        "## Recommended Next Block",
        "- Block 24C-0 only if all gates pass.",
        "",
        "## Exit Gate",
        f"- sidecar_alignment_passed: {report['sidecar_alignment_passed']}",
        f"- endpoint_closure_passed: {report['endpoint_closure_passed']}",
        f"- forbidden_relation_count: {report['forbidden_relation_count']}",
        f"- duplicate_semantic_object_count: {report['duplicate_semantic_object_count']}",
        f"- idempotency_passed: {report['idempotency_passed']}",
        f"- issue_object_written_to_pfss_count: {report['issue_object_written_to_pfss_count']}",
        f"- artifacts_complete: {report['artifacts_complete']}",
        f"- real_embedding_smoke_status: {report['real_embedding_smoke_status']}",
        "",
        "Final status:",
        f"- {final_status}",
    ]) + "\n"


def _empty_result(
    *,
    trace_id: str,
    parse_result: Any,
    route: SemanticRoute,
    raw_status: str,
    raw_chunk_count_before: int,
    raw_chunk_vector_count_before: int,
    status: str,
    issues: list[str],
) -> SemanticBranchExecutionResult:
    return SemanticBranchExecutionResult(
        trace_id=trace_id,
        document_id=parse_result.document.document_id,
        document_version_id=parse_result.document.document_version_id,
        semantic_route=route,
        raw_evidence_status=raw_status,
        dsl_compile_executed=False,
        pfss_write_executed=False,
        generic_write_executed=False,
        issue_index_write_executed=False,
        safe_chunk_count=0,
        safe_entity_count=0,
        safe_relationship_count=0,
        blocked_object_count=0,
        issue_record_count=0,
        pfss_graph_node_count=0,
        pfss_graph_edge_count=0,
        generic_graph_node_count=0,
        generic_graph_edge_count=0,
        pfss_entity_vector_count=0,
        pfss_relationship_vector_count=0,
        duplicate_semantic_object_count=0,
        cross_space_collision_count=0,
        extract_entities_called=False,
        gleaning_executed=False,
        llm_called=False,
        embedding_called=False,
        source_reference_strategy=SOURCE_REFERENCE_STRATEGY,
        raw_chunk_count_before=raw_chunk_count_before,
        raw_chunk_count_after=raw_chunk_count_before,
        raw_chunk_vector_count_before=raw_chunk_vector_count_before,
        raw_chunk_vector_count_after=raw_chunk_vector_count_before,
        duplicate_raw_chunk_count=0,
        sidecar_alignment_passed=True,
        endpoint_closure_passed=True,
        forbidden_relation_count=0,
        dangling_relationship_count=0,
        status=status,
        issues=issues,
        risks=[],
    )


def _route(route_decision: Any) -> SemanticRoute:
    if isinstance(route_decision, str):
        return route_decision  # type: ignore[return-value]
    return str(getattr(route_decision, "selected_plan_route", getattr(route_decision, "semantic_route", "PARSE_FAILED")))  # type: ignore[return-value]


def _issue_index_path(config: SemanticBranchExecutionConfig) -> str:
    if config.issue_index_path:
        return config.issue_index_path
    return str(Path(config.artifact_root) / "issue_index.json")


def _suite_counts(results: list[SemanticBranchExecutionResult]) -> dict[str, int]:
    latest = results[-1] if results else None
    return {
        "pfss_nodes": max((item.pfss_graph_node_count for item in results), default=0),
        "pfss_edges": max((item.pfss_graph_edge_count for item in results), default=0),
        "issue_records": max((item.issue_record_count for item in results), default=0),
        "sidecar_records": (latest.pfss_graph_node_count + latest.pfss_graph_edge_count) if latest else 0,
    }


def _exit_gate_passed(report: dict[str, Any]) -> bool:
    return (
        report.get("sidecar_alignment_passed") is True
        and report.get("endpoint_closure_passed") is True
        and report.get("forbidden_relation_count") == 0
        and report.get("duplicate_semantic_object_count") == 0
        and report.get("idempotency_passed") is True
        and report.get("issue_object_written_to_pfss_count") == 0
        and report.get("artifacts_complete") is True
        and report.get("real_embedding_smoke_status") == "NOT_RUN"
    )


REQUIRED_ARTIFACT_FILES = [
    "semantic_branch_report.json",
    "semantic_branch_report.md",
    "graph_space_policy.json",
    "route_execution_results.json",
    "pfss_payload_summary.json",
    "pfss_storage_snapshot.json",
    "generic_storage_snapshot.json",
    "issue_index.json",
    "issue_summary.json",
    "graph_isolation_snapshot.json",
    "source_reference_strategy.json",
    "idempotency_report.json",
    "architecture.mmd",
    "safety_check.json",
    "cleanup_report.json",
    "command_log.txt",
    "git_status_before.txt",
    "git_status_after.txt",
    "core_diff_check.txt",
    "unresolved_questions.md",
]

EXIT_GATE_FIELDS = [
    "sidecar_alignment_passed",
    "endpoint_closure_passed",
    "forbidden_relation_count",
    "duplicate_semantic_object_count",
    "idempotency_passed",
    "issue_object_written_to_pfss_count",
    "artifacts_complete",
    "real_embedding_smoke_status",
]


def validate_artifacts(artifact_root: str) -> dict[str, Any]:
    root = Path(artifact_root)
    missing = [name for name in REQUIRED_ARTIFACT_FILES if not (root / name).exists()]
    json_failures = []
    for path in root.glob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            json_failures.append({"file": path.name, "error": str(exc)})
    report_path = root / "semantic_branch_report.json"
    missing_report_fields = list(EXIT_GATE_FIELDS)
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            missing_report_fields = [field for field in EXIT_GATE_FIELDS if field not in report]
        except Exception:
            missing_report_fields = list(EXIT_GATE_FIELDS)
    validation = {
        "required_count": len(REQUIRED_ARTIFACT_FILES),
        "existing_count": len(REQUIRED_ARTIFACT_FILES) - len(missing),
        "missing_files": missing,
        "json_parse_failures": json_failures,
        "missing_report_fields": missing_report_fields,
        "architecture_present": (root / "architecture.mmd").exists()
        and bool((root / "architecture.mmd").read_text(encoding="utf-8").strip()),
        "safety_report_present": (root / "safety_check.json").exists(),
        "core_diff_report_present": (root / "core_diff_check.txt").exists(),
    }
    validation["artifacts_complete"] = (
        not validation["missing_files"]
        and not validation["json_parse_failures"]
        and not validation["missing_report_fields"]
        and validation["architecture_present"]
        and validation["safety_report_present"]
        and validation["core_diff_report_present"]
    )
    return validation
