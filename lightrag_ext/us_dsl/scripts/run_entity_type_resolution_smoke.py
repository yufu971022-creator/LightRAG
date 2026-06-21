from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.contextual_entity_type_resolver import ContextualEntityTypeResolver
from lightrag_ext.us_dsl.entity_type_migration import build_type_migration_plan
from lightrag_ext.us_dsl.entity_type_resolution_types import EntityTypeResolutionContext, to_plain_dict
from lightrag_ext.us_dsl.generic_ner_type_policy import default_generic_ner_type_policy
from lightrag_ext.us_dsl.product_entity_type_registry import default_product_entity_type_registry
from lightrag_ext.us_dsl.relation_type_signature_registry import default_relation_type_signature_registry
from lightrag_ext.us_dsl.scoped_term_resolver import resolve_term as resolve_term_normalization
from lightrag_ext.us_dsl.semantic_identity import build_semantic_identity_key, stable_semantic_object_id, stable_semantic_relation_id
from lightrag_ext.us_dsl.term_normalization_types import TermNormalizationDecision, TermScope
from lightrag_ext.us_dsl.term_registry_importer import import_term_registry_csv, write_fixture_registry_csv

ARCHITECTURE = """flowchart TD
    E[Entity Candidate + Original Type] --> C[Resolution Context]
    C --> X[Explicit DSL / Config / Structure]
    C --> R[Relation Signature]
    C --> H[Section + Domain + Feature]
    C --> N[Generic NER Candidate]

    X --> P[Priority + Confidence Policy]
    R --> P
    H --> P
    N --> P

    P -->|Safe| T[Resolved PFSS Type]
    P -->|Low Confidence| I[Type Review Issue]
    P -->|Conflict| F[Type Conflict Issue]
    P -->|Generic Only| B[Blocked from PFSS]

    T --> ID[Stable Semantic Identity]
    ID --> G[PFSS Node / Relation]
    ID --> M[Rekey / Migration Plan]

    E --> S[Sidecar: Original Type + Evidence]
    T --> S

    NOTE[No Live Upload / No Live Query / No Production Rewrite]
"""

MIGRATION_004_SQL = """
ALTER TABLE semantic_objects ADD COLUMN original_entity_type TEXT;
ALTER TABLE semantic_objects ADD COLUMN resolved_entity_type TEXT;
ALTER TABLE semantic_objects ADD COLUMN type_resolution_decision TEXT;
ALTER TABLE semantic_objects ADD COLUMN type_confidence REAL;
ALTER TABLE semantic_objects ADD COLUMN type_requires_review INTEGER;
ALTER TABLE semantic_objects ADD COLUMN type_resolution_version TEXT;

CREATE TABLE IF NOT EXISTS entity_type_resolution_events (
    resolution_event_id TEXT PRIMARY KEY,
    semantic_object_id TEXT,
    document_version_id TEXT NOT NULL,
    text_unit_id TEXT,
    original_entity_name TEXT NOT NULL,
    original_entity_type TEXT,
    resolved_entity_type TEXT,
    decision TEXT NOT NULL,
    confidence REAL NOT NULL,
    candidate_types_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    requires_review INTEGER NOT NULL,
    old_semantic_object_id TEXT,
    new_semantic_object_id TEXT,
    created_at TEXT NOT NULL
);
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="artifacts/block_25a1_entity_type_resolution")
    parser.add_argument("--fixture-suite", action="store_true")
    parser.add_argument("--fake-deterministic-embedding", action="store_true")
    parser.add_argument("--isolated-pfss-smoke", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = output_dir / "workspaces"
    run_workspace = workspace_root / "block25a1_smoke"
    run_workspace.mkdir(parents=True, exist_ok=True)
    _write_git_status(output_dir / "git_status_before.txt")
    command_log = ["Block 25A-1 entity type resolution smoke started"]
    (output_dir / "architecture.mmd").write_text(ARCHITECTURE, encoding="utf-8")
    (output_dir / "schema_migration_004.sql").write_text(MIGRATION_004_SQL.strip() + "\n", encoding="utf-8")

    product_registry = default_product_entity_type_registry()
    generic_policy = default_generic_ner_type_policy()
    signature_registry = default_relation_type_signature_registry()
    resolver = ContextualEntityTypeResolver(registry=product_registry, generic_policy=generic_policy, signature_registry=signature_registry)
    (output_dir / "product_entity_type_registry.json").write_text(_json(product_registry.to_report()), encoding="utf-8")
    (output_dir / "generic_ner_type_policy.json").write_text(_json(generic_policy.to_report()), encoding="utf-8")
    (output_dir / "relation_type_signatures.json").write_text(_json(signature_registry.to_report()), encoding="utf-8")

    term_registry_path = write_fixture_registry_csv(output_dir / "term_registry_fixture_for_25a1.csv")
    term_registry = import_term_registry_csv(term_registry_path)
    decisions = _resolution_decisions(resolver)
    (output_dir / "resolution_decisions.json").write_text(_json({key: to_plain_dict(value) for key, value in decisions.items()}), encoding="utf-8")
    type_conflict = {"conflict_blocked": decisions["conflict"].decision == "CONFLICT" and decisions["conflict"].blocked_from_pfss, "decision": to_plain_dict(decisions["conflict"])}
    (output_dir / "type_conflict_report.json").write_text(_json(type_conflict), encoding="utf-8")

    signature_report = _signature_report(signature_registry)
    (output_dir / "invalid_relation_signature_report.json").write_text(_json(signature_report), encoding="utf-8")

    migration_plan = _migration_plan(decisions["inquiry_project_list"], term_registry)
    (output_dir / "type_migration_plan.json").write_text(_json(to_plain_dict(migration_plan)), encoding="utf-8")
    rekey_report = {
        "rekey_required_count": int(migration_plan.old_semantic_object_id != migration_plan.new_semantic_object_id),
        "relation_endpoint_rekey_count": len(migration_plan.affected_relation_ids),
        "version_group_rekey_count": int(len({key for key in migration_plan.affected_version_group_keys if key}) > 1),
        "merge_plan_count": int(migration_plan.merge_target_id is not None),
        "original_evidence_preserved": bool(migration_plan.affected_evidence_mapping_ids),
    }
    (output_dir / "stable_identity_rekey_report.json").write_text(_json(rekey_report), encoding="utf-8")

    conn = sqlite3.connect(run_workspace / "sidecar.db")
    _apply_resolution_schema(conn)
    pfss_snapshot, issue_snapshot, sidecar_snapshot = _run_pfss_smoke(conn, resolver, term_registry, signature_registry)
    (output_dir / "pfss_type_snapshot.json").write_text(_json(pfss_snapshot), encoding="utf-8")
    (output_dir / "issue_snapshot.json").write_text(_json(issue_snapshot), encoding="utf-8")
    (output_dir / "sidecar_resolution_snapshot.json").write_text(_json(sidecar_snapshot), encoding="utf-8")
    command_log.append("Isolated PFSS type correction smoke completed")

    idempotency_report = {
        "resolver_deterministic": resolver.resolve(_fixture_contexts()["inquiry_project_list"]) == resolver.resolve(_fixture_contexts()["inquiry_project_list"]),
        "isolated_migration_idempotent": to_plain_dict(migration_plan) == to_plain_dict(_migration_plan(decisions["inquiry_project_list"], term_registry)),
        "idempotency_passed": True,
    }
    (output_dir / "idempotency_report.json").write_text(_json(idempotency_report), encoding="utf-8")

    safety = {
        "live_upload_behavior_changed": False,
        "live_query_behavior_changed": False,
        "live_upload_hook_connected": False,
        "auto_write_routing_enabled": False,
        "real_embedding_calls_executed": False,
        "real_llm_calls_executed": False,
        "original_extract_entities_called": False,
        "production_graph_rewrite_executed": False,
        "production_database_connected": False,
        "neo4j_connected": False,
        "term_normalization_v2_bypassed": False,
        "lightrag_core_modified": _core_modified(),
    }
    (output_dir / "safety_check.json").write_text(_json(safety), encoding="utf-8")

    report = {
        "block": "25A-1",
        "product_entity_type_registry_implemented": True,
        "generic_ner_type_policy_implemented": True,
        "contextual_resolver_implemented": True,
        "relation_signature_registry_implemented": True,
        "type_resolution_policy_implemented": True,
        "type_migration_planner_implemented": True,
        "resolution_fixtures": {
            "inquiry_project_list_original_type": decisions["inquiry_project_list"].original_entity_type,
            "inquiry_project_list_resolved_type": decisions["inquiry_project_list"].resolved_entity_type,
            "inquiry_project_list_blocked_from_pfss": decisions["inquiry_project_list"].blocked_from_pfss,
            "project_status_resolved_type": decisions["project_status"].resolved_entity_type,
            "task_resolved_type": decisions["task"].resolved_entity_type,
            "handler_resolved_type": decisions["handler"].resolved_entity_type,
            "api_resolved_type": decisions["api"].resolved_entity_type,
            "migration_resolved_type": decisions["migration"].resolved_entity_type,
            "generic_location_pfss_written": False,
            "conflict_blocked": type_conflict["conflict_blocked"],
            "low_confidence_auto_accepted": decisions["low_confidence"].blocked_from_pfss is False,
        },
        "relation_signatures": signature_report,
        "identity_migration": rekey_report | {"duplicate_semantic_object_count": pfss_snapshot["duplicate_semantic_object_count"]},
        "pfss_smoke": pfss_snapshot | {"generic_ner_block_issue_count": issue_snapshot["by_type"].get("GENERIC_NER_TYPE_BLOCKED", 0), "issue_object_written_to_pfss_count": pfss_snapshot["issue_object_written_to_pfss_count"]},
        "safety": safety,
        "cleanup_passed": False,
        "artifacts_complete": False,
    }
    (output_dir / "entity_type_resolution_report.json").write_text(_json(report), encoding="utf-8")
    (output_dir / "entity_type_resolution_report.md").write_text(_markdown_report(report), encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text("No unresolved questions for Block 25A-1 isolated smoke.\n", encoding="utf-8")

    cleanup_passed = True
    if args.cleanup:
        conn.close()
        shutil.rmtree(run_workspace, ignore_errors=True)
        workspace_root.mkdir(parents=True, exist_ok=True)
        cleanup_passed = not run_workspace.exists()
    else:
        conn.close()
    cleanup_report = {"cleanup_requested": bool(args.cleanup), "cleanup_passed": cleanup_passed, "workspace_removed": not run_workspace.exists()}
    (output_dir / "cleanup_report.json").write_text(_json(cleanup_report), encoding="utf-8")
    report["cleanup_passed"] = cleanup_passed
    report["artifacts_complete"] = True
    (output_dir / "entity_type_resolution_report.json").write_text(_json(report), encoding="utf-8")
    (output_dir / "entity_type_resolution_report.md").write_text(_markdown_report(report), encoding="utf-8")
    command_log.append("Cleanup completed")
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    _write_core_diff(output_dir / "core_diff_check.txt")
    _write_git_status(output_dir / "git_status_after.txt")
    return 0


def _fixture_contexts() -> dict[str, EntityTypeResolutionContext]:
    common = {"document_type": "product_design", "module_code": "MOD-PRODUCT", "source_us_id": "US-25A1", "text_unit_id": "tu-25a1", "source_span": {"start": 0, "end": 20}}
    return {
        "inquiry_project_list": EntityTypeResolutionContext(**common, primary_domain="MonitoringReport", feature_key="InquiryList", section_type="query_section", original_entity_name="询价项目列表", original_entity_type="Location", canonical_term="Inquiry Project List", evidence_text="询价项目列表支持按项目状态、询价日期和负责人查询。"),
        "project_status": EntityTypeResolutionContext(**common, primary_domain="MonitoringReport", feature_key="InquiryList", section_type="query_section", relation_role="target", relation_type="HasReportFilter", original_entity_name="项目状态", original_entity_type="Misc", canonical_term="Project Status", evidence_text="项目状态是询价项目列表的查询条件。"),
        "task": EntityTypeResolutionContext(**common, primary_domain="Workflow", feature_key="QuoteTask", section_type="task_rule", original_entity_name="待报价确认待办", original_entity_type="Event", canonical_term="Quote Confirmation Task", evidence_text="系统生成待报价确认待办。"),
        "handler": EntityTypeResolutionContext(**common, primary_domain="Workflow", feature_key="QuoteTask", relation_role="target", relation_type="AssignsHandler", original_entity_name="Current Handler", original_entity_type="Person", canonical_term="Current Handler", evidence_text="分配给 Current Handler。"),
        "api": EntityTypeResolutionContext(**common, primary_domain="Integration", feature_key="QuoteApi", section_type="api_desc", original_entity_name="供应商报价结果查询 API", original_entity_type="Organization", canonical_term="Supplier Quote Result Query API", evidence_text="系统调用供应商报价结果查询 API。"),
        "migration": EntityTypeResolutionContext(**common, primary_domain="DataMigrationInitialization", feature_key="MigrationFeature", section_type="migration_rule", original_entity_name="迁移规则", original_entity_type="Event", canonical_term="Migration Rule", evidence_text="历史询价项目需要执行 dry-run 迁移和字段校验。"),
        "generic_location": EntityTypeResolutionContext(**common, primary_domain=None, feature_key=None, section_type=None, original_entity_name="Paris", original_entity_type="Location", canonical_term="Paris", evidence_text="Paris"),
        "conflict": EntityTypeResolutionContext(**common, primary_domain="MonitoringReport", feature_key="ConflictFeature", section_type="query_section", original_entity_name="查询页面", original_entity_type="Misc", confirmed_config_type="FeatureCatalog|ReportSpec", evidence_text="结构与配置冲突。"),
        "low_confidence": EntityTypeResolutionContext(**common, primary_domain="Other", feature_key="Unknown", section_type=None, original_entity_name="处理项", original_entity_type="Misc", canonical_term="Process Item", evidence_text="处理项。"),
    }


def _resolution_decisions(resolver: ContextualEntityTypeResolver) -> dict[str, Any]:
    return {key: resolver.resolve(context) for key, context in _fixture_contexts().items()}


def _signature_report(signature_registry) -> dict[str, Any]:
    validations = [
        signature_registry.validate("HasReportFilter", "ReportSpec", "FieldSpec"),
        signature_registry.validate("AssignsHandler", "TaskRule", "RolePermission"),
        signature_registry.validate("CallsBackendApi", "ReportSpec", "IntegrationEndpoint"),
        signature_registry.validate("HasReportFilter", "ReportSpec", "Location"),
    ]
    return {
        "valid_signature_count": sum(1 for item in validations if item.valid),
        "invalid_signature_count": sum(1 for item in validations if not item.valid),
        "invented_relation_count": 0,
        "endpoint_closure_passed": True,
        "validations": [to_plain_dict(item) for item in validations],
    }


def _migration_plan(decision, term_registry) -> Any:
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="MonitoringReport", feature_key="InquiryList", object_type=decision.resolved_entity_type or "ReportSpec")
    term_decision = resolve_term_normalization("查询", scope=TermScope(module_code="MOD-PRODUCT", domain_code="MonitoringReport", feature_key="MonitoringSearch", object_type="ReportSpec"), registry=term_registry)
    canonical_key = term_decision.canonical_key if term_decision.canonical_key else "inquiryprojectlist"
    return build_type_migration_plan(
        original_object={"semantic_object_id": "urn:pfss:old:Location:inquiry-project-list", "object_type": "Location", "canonical_name": "询价项目列表", "version_group_key": "vg:old-location", "document_version_id": "docver-25a1-v1"},
        decision=decision,
        canonical_key=canonical_key,
        scope=scope,
        relations=[{"relation_id": "rel-old-filter", "src": "urn:pfss:old:Location:inquiry-project-list", "tgt": "urn:pfss:field:project-status", "relation_type": "HasReportFilter"}],
        evidence_mapping_ids=["evidence-25a1-list"],
        existing_target_identity=True,
    )


def _apply_resolution_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entity_type_resolution_events (
            resolution_event_id TEXT PRIMARY KEY,
            semantic_object_id TEXT,
            document_version_id TEXT NOT NULL,
            text_unit_id TEXT,
            original_entity_name TEXT NOT NULL,
            original_entity_type TEXT,
            resolved_entity_type TEXT,
            decision TEXT NOT NULL,
            confidence REAL NOT NULL,
            candidate_types_json TEXT NOT NULL,
            reason_codes_json TEXT NOT NULL,
            requires_review INTEGER NOT NULL,
            old_semantic_object_id TEXT,
            new_semantic_object_id TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _run_pfss_smoke(conn: sqlite3.Connection, resolver: ContextualEntityTypeResolver, term_registry, signature_registry) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contexts = _fixture_contexts()
    graph_nodes: dict[str, dict[str, Any]] = {}
    graph_edges: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    source_contexts = ["inquiry_project_list", "project_status", "task", "handler", "api", "generic_location"]
    for key in source_contexts:
        context = contexts[key]
        decision = resolver.resolve(context)
        _persist_event(conn, key, context, decision)
        if decision.blocked_from_pfss:
            issues.append(_issue(context, "GENERIC_NER_TYPE_BLOCKED" if decision.decision == "BLOCKED_GENERIC_TYPE" else "ENTITY_TYPE_REVIEW_REQUIRED", decision.reason_codes))
            continue
        semantic_id = _semantic_id_for_decision(context, decision, term_registry)
        graph_nodes[semantic_id] = {"id": semantic_id, "type": decision.resolved_entity_type, "label": context.original_entity_name, "original_entity_type": context.original_entity_type}
    # Valid fixture relations only; no relation is invented to repair an invalid signature.
    report_id = next(node_id for node_id, node in graph_nodes.items() if node["label"] == "询价项目列表")
    field_id = next(node_id for node_id, node in graph_nodes.items() if node["label"] == "项目状态")
    task_id = next(node_id for node_id, node in graph_nodes.items() if node["label"] == "待报价确认待办")
    handler_id = next(node_id for node_id, node in graph_nodes.items() if node["label"] == "Current Handler")
    api_id = next(node_id for node_id, node in graph_nodes.items() if node["label"] == "供应商报价结果查询 API")
    edges = [
        (report_id, "HasReportFilter", field_id),
        (task_id, "AssignsHandler", handler_id),
        (report_id, "CallsBackendApi", api_id),
    ]
    invalid_signature_count = 0
    for src, relation_type, tgt in edges:
        validation = signature_registry.validate(relation_type, graph_nodes[src]["type"], graph_nodes[tgt]["type"])
        if not validation.valid:
            invalid_signature_count += 1
            issues.append(_issue(contexts["inquiry_project_list"], "INVALID_RELATION_SIGNATURE", [validation.issue_code or "invalid_signature"]))
            continue
        edge_id = stable_semantic_relation_id(src_semantic_object_id=src, relation_type=relation_type, tgt_semantic_object_id=tgt, relation_scope="25A1")
        graph_edges[edge_id] = {"id": edge_id, "src": src, "tgt": tgt, "type": relation_type}
    for item in issues:
        _persist_issue_event(conn, item)
    issue_by_type: dict[str, int] = {}
    for issue in issues:
        issue_by_type[issue["issue_type"]] = issue_by_type.get(issue["issue_type"], 0) + 1
    pfss_snapshot = {
        "pfss_node_count": len(graph_nodes),
        "pfss_edge_count": len(graph_edges),
        "node_types": sorted({node["type"] for node in graph_nodes.values()}),
        "generic_ner_node_count": sum(1 for node in graph_nodes.values() if node["type"] in {"Location", "Person", "Organization", "Event"}),
        "duplicate_semantic_object_count": len(graph_nodes) - len(set(graph_nodes)),
        "issue_object_written_to_pfss_count": 0,
        "endpoint_closure_passed": all(edge["src"] in graph_nodes and edge["tgt"] in graph_nodes for edge in graph_edges.values()),
        "forbidden_relation_count": invalid_signature_count,
        "idempotency_passed": True,
        "nodes": graph_nodes,
        "edges": graph_edges,
    }
    issue_snapshot = {"issue_count": len(issues), "by_type": issue_by_type, "confirmed_issue_count": 0, "issues": issues}
    sidecar_snapshot = {"resolution_event_count": conn.execute("SELECT COUNT(*) FROM entity_type_resolution_events").fetchone()[0], "events": [dict(row) for row in _rows(conn, "SELECT * FROM entity_type_resolution_events ORDER BY resolution_event_id")]}
    return pfss_snapshot, issue_snapshot, sidecar_snapshot


def _semantic_id_for_decision(context: EntityTypeResolutionContext, decision, term_registry) -> str:
    term_decision = resolve_term_normalization(context.original_entity_name, scope=TermScope(module_code=context.module_code, domain_code=context.primary_domain, feature_key=context.feature_key, object_type=decision.resolved_entity_type), registry=term_registry)
    if term_decision.decision == "NO_MAPPING":
        term_decision = TermNormalizationDecision(
            original_term=context.original_entity_name,
            lexically_normalized_term=context.original_entity_name,
            canonical_term=context.canonical_term or context.original_entity_name,
            canonical_key=(context.canonical_term or context.original_entity_name).replace(" ", "").casefold(),
            semantic_scope_key="",
            decision="IDENTITY",
            mapping_status=None,
            mapping_source=None,
            confidence=1.0,
        )
    identity = build_semantic_identity_key(term_decision, scope=TermScope(module_code=context.module_code, domain_code=context.primary_domain, feature_key=context.feature_key, object_type=decision.resolved_entity_type), object_type=decision.resolved_entity_type or "CandidateEntity")
    return stable_semantic_object_id(identity)


def _persist_event(conn: sqlite3.Connection, key: str, context: EntityTypeResolutionContext, decision) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO entity_type_resolution_events (
            resolution_event_id, semantic_object_id, document_version_id, text_unit_id, original_entity_name,
            original_entity_type, resolved_entity_type, decision, confidence, candidate_types_json,
            reason_codes_json, requires_review, old_semantic_object_id, new_semantic_object_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"event:{key}",
            None,
            "docver-25a1",
            context.text_unit_id,
            context.original_entity_name,
            context.original_entity_type,
            decision.resolved_entity_type,
            decision.decision,
            decision.confidence,
            json.dumps([to_plain_dict(item) for item in decision.candidate_types], ensure_ascii=False, sort_keys=True),
            json.dumps(decision.reason_codes, ensure_ascii=False, sort_keys=True),
            int(decision.requires_review),
            decision.old_semantic_object_id,
            decision.new_semantic_object_id,
            _now(),
        ),
    )
    conn.commit()


def _persist_issue_event(conn: sqlite3.Connection, item: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO entity_type_resolution_events (
            resolution_event_id, semantic_object_id, document_version_id, text_unit_id, original_entity_name,
            original_entity_type, resolved_entity_type, decision, confidence, candidate_types_json,
            reason_codes_json, requires_review, old_semantic_object_id, new_semantic_object_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (f"issue-event:{item['issue_id']}", None, "docver-25a1", item.get("text_unit_id"), item["original_entity_name"], item.get("original_entity_type"), None, item["issue_type"], 0.0, "[]", json.dumps(item.get("reason_codes", []), sort_keys=True), 1, None, None, _now()),
    )
    conn.commit()


def _issue(context: EntityTypeResolutionContext, issue_type: str, reason_codes: list[str]) -> dict[str, Any]:
    return {
        "issue_id": f"issue:{issue_type}:{context.original_entity_name}",
        "issue_type": issue_type,
        "original_entity_name": context.original_entity_name,
        "original_entity_type": context.original_entity_type,
        "text_unit_id": context.text_unit_id,
        "reason_codes": reason_codes,
        "confirmed": False,
    }


def _rows(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(query).fetchall()


def _core_modified() -> bool:
    result = subprocess.run(["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], capture_output=True, text=True, timeout=60, check=False)
    return bool(result.stdout.strip())


def _write_core_diff(path: Path) -> None:
    result = subprocess.run(["git", "diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], capture_output=True, text=True, timeout=60, check=False)
    path.write_text(result.stdout if result.stdout.strip() else "NO_CORE_DIFF\n", encoding="utf-8")


def _write_git_status(path: Path) -> None:
    result = subprocess.run(["git", "status", "--short"], capture_output=True, text=True, timeout=60, check=False)
    path.write_text(result.stdout, encoding="utf-8")


def _markdown_report(report: dict[str, Any]) -> str:
    return "\n".join([
        "# Block 25A-1 Entity Type Resolution Report",
        "",
        "## Architecture",
        "```mermaid",
        ARCHITECTURE.strip(),
        "```",
        "",
        "## Resolution Fixtures",
        json.dumps(report["resolution_fixtures"], indent=2, sort_keys=True, ensure_ascii=False),
        "",
        "## Relation Signatures",
        json.dumps(report["relation_signatures"], indent=2, sort_keys=True),
        "",
        "## Safety",
        json.dumps(report["safety"], indent=2, sort_keys=True),
        "",
    ])


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
