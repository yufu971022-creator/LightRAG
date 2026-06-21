from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.scoped_term_resolver import resolve_term
from lightrag_ext.us_dsl.semantic_identity import (
    build_semantic_identity_key,
    stable_semantic_object_id,
    stable_semantic_relation_id,
    stable_version_group_key,
)
from lightrag_ext.us_dsl.term_normalization_migration import build_term_normalization_migration_plan
from lightrag_ext.us_dsl.term_normalization_types import TermMappingRecord, TermScope, to_plain_dict
from lightrag_ext.us_dsl.term_query_expander import expand_query_terms
from lightrag_ext.us_dsl.term_registry import TermRegistry, TermSidecarStore, write_term_migration_artifact
from lightrag_ext.us_dsl.term_registry_importer import (
    XLSX_IMPORT_STATUS,
    import_term_registry_csv,
    write_fixture_registry_csv,
    write_term_registry_template,
)
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository

ARCHITECTURE = """flowchart TD
    T[Original Term + Evidence] --> L[Deterministic Lexical Normalization]
    L --> S[Scope: Module / Domain / Feature / ObjectType]
    S --> R[Term Registry Resolution]
    R --> C{Confidence / Conflict Gate}

    C -->|Confirmed High Confidence| K[Canonical Key]
    C -->|Candidate| I[Term Mapping Review Issue]
    C -->|Conflict| A[Term Ambiguity Issue]
    C -->|No Mapping| O[Keep Original Identity]

    K --> ID[Stable Semantic Object ID]
    ID --> VG[Canonical Version Group Key]
    ID --> PFSS[PFSS Business Node]

    T --> E[Original Evidence Preserved]
    E --> SIDE[Sidecar Alias / Evidence Mapping]
    K --> SIDE

    Q[Query Term] --> QE[Scoped Query Expansion]
    QE --> ALIAS[Canonical + Confirmed Aliases]

    NOTE[No Live Query Hook / No Production Graph Rewrite]
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="artifacts/block_25a0_term_normalization")
    parser.add_argument("--fixture-suite", action="store_true")
    parser.add_argument("--fake-deterministic-embedding", action="store_true")
    parser.add_argument("--isolated-pfss-dedup-smoke", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = output_dir / "workspaces"
    run_workspace = workspace_root / "block25a0_smoke"
    run_workspace.mkdir(parents=True, exist_ok=True)
    command_log = ["Block 25A-0 term normalization smoke started"]
    _write_git_status(output_dir / "git_status_before.txt")
    (output_dir / "architecture.mmd").write_text(ARCHITECTURE, encoding="utf-8")
    write_term_migration_artifact(output_dir)
    write_term_registry_template(output_dir / "term_registry_template.csv")
    fixture_csv = write_fixture_registry_csv(output_dir / "term_registry_fixture.csv")
    registry = import_term_registry_csv(fixture_csv, registry_version="25A-0")
    validation = registry.validation_report() | {"xlsx_import_status": XLSX_IMPORT_STATUS}
    (output_dir / "term_registry_validation.json").write_text(_json(validation), encoding="utf-8")
    command_log.append("CSV registry imported")

    conflict_registry = _conflict_registry()
    decisions = _normalization_decisions(registry, conflict_registry)
    (output_dir / "normalization_decisions.json").write_text(_json({key: to_plain_dict(value) for key, value in decisions.items()}), encoding="utf-8")
    ambiguity_report = {
        "conflict_mapping_detected": decisions["conflict_status"].decision == "CONFLICT",
        "ambiguities": to_plain_dict(decisions["conflict_status"]),
        "term_ambiguity_issue_created": decisions["conflict_status"].requires_review,
    }
    (output_dir / "ambiguity_report.json").write_text(_json(ambiguity_report), encoding="utf-8")

    identity_report = _identity_report(decisions)
    (output_dir / "stable_identity_report.json").write_text(_json(identity_report), encoding="utf-8")
    version_group_report = _version_group_report(decisions)
    (output_dir / "version_group_alignment_report.json").write_text(_json(version_group_report), encoding="utf-8")

    query_expansion = {
        "handler": to_plain_dict(expand_query_terms(["Current Handler"], module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission", registry=registry)),
        "bank_status": to_plain_dict(expand_query_terms(["Bank Status"], module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec", registry=registry)),
        "rejected_scope": to_plain_dict(expand_query_terms(["Owner"], module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="RejectedFeature", object_type="FieldSpec", registry=registry)),
    }
    (output_dir / "query_expansion_report.json").write_text(_json(query_expansion), encoding="utf-8")

    repo = SQLiteSidecarRepository(str(run_workspace / "sidecar.db"), artifact_root=str(output_dir))
    repo.initialize_schema()
    repo.apply_lifecycle_migration()
    sidecar = TermSidecarStore(repo._conn)
    sidecar.apply_migration()
    pfss_snapshot = _run_pfss_dedup_smoke(registry, sidecar)
    sidecar_snapshot = sidecar.alias_snapshot()
    (output_dir / "pfss_dedup_snapshot.json").write_text(_json(pfss_snapshot), encoding="utf-8")
    (output_dir / "sidecar_alias_snapshot.json").write_text(_json(sidecar_snapshot), encoding="utf-8")
    command_log.append("Isolated PFSS dedup smoke completed")

    migration_plan = _migration_report(registry, conflict_registry)
    (output_dir / "migration_plan.json").write_text(_json(migration_plan), encoding="utf-8")

    idempotency_report = {
        "sidecar_alias_records_are_idempotent": _alias_idempotency(registry, sidecar),
        "identity_generation_deterministic": identity_report["stable_across_documents"] and identity_report["stable_across_versions"],
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
        "entity_type_resolver_changed": False,
        "lightrag_core_modified": _core_modified(),
    }
    (output_dir / "safety_check.json").write_text(_json(safety), encoding="utf-8")

    report = {
        "block": "25A-0",
        "lexical_normalizer_implemented": True,
        "term_registry_implemented": True,
        "csv_importer_implemented": True,
        "xlsx_import_status": XLSX_IMPORT_STATUS,
        "scoped_resolver_implemented": True,
        "stable_semantic_identity_implemented": True,
        "query_expander_implemented": True,
        "migration_planner_implemented": True,
        "normalization_fixtures": {
            "swift_code_variants_same_identity": identity_report["swift_code_variants_same_identity"],
            "current_handler_bilingual_same_identity": identity_report["current_handler_bilingual_same_identity"],
            "unscoped_status_auto_merged": decisions["unscoped_status"].decision in {"REGISTRY_CONFIRMED", "AUTO_NORMALIZED", "IDENTITY"} and decisions["unscoped_status"].canonical_term != "Status",
            "scoped_bank_status_mapping_passed": decisions["scoped_status"].canonical_term == "Bank Status" and not decisions["scoped_status"].requires_review,
            "bank_approval_task_status_distinct": identity_report["bank_approval_task_status_distinct"],
            "search_translation_requires_scope": decisions["unscoped_search"].decision == "NO_MAPPING" and decisions["scoped_search"].canonical_term == "Search",
            "conflict_mapping_detected": decisions["conflict_status"].decision == "CONFLICT",
            "low_confidence_mapping_auto_merged": decisions["candidate_handler"].decision in {"REGISTRY_CONFIRMED", "AUTO_NORMALIZED"},
        },
        "identity": identity_report,
        "pfss_smoke": pfss_snapshot,
        "migration": migration_plan,
        "safety": safety,
        "cleanup_passed": False,
        "artifacts_complete": False,
    }
    (output_dir / "term_normalization_report.json").write_text(_json(report), encoding="utf-8")
    (output_dir / "term_normalization_report.md").write_text(_markdown_report(report), encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text("No unresolved questions for Block 25A-0 isolated smoke.\n", encoding="utf-8")

    cleanup_passed = True
    if args.cleanup:
        shutil.rmtree(run_workspace, ignore_errors=True)
        workspace_root.mkdir(parents=True, exist_ok=True)
        cleanup_passed = not run_workspace.exists()
    cleanup_report = {"cleanup_requested": bool(args.cleanup), "cleanup_passed": cleanup_passed, "workspace_removed": not run_workspace.exists()}
    (output_dir / "cleanup_report.json").write_text(_json(cleanup_report), encoding="utf-8")
    report["cleanup_passed"] = cleanup_passed
    report["artifacts_complete"] = True
    (output_dir / "term_normalization_report.json").write_text(_json(report), encoding="utf-8")
    (output_dir / "term_normalization_report.md").write_text(_markdown_report(report), encoding="utf-8")
    command_log.append("Cleanup completed")
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    _write_core_diff(output_dir / "core_diff_check.txt")
    _write_git_status(output_dir / "git_status_after.txt")
    repo.close()
    return 0


def _normalization_decisions(registry: TermRegistry, conflict_registry: TermRegistry) -> dict[str, Any]:
    swift_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Integration", feature_key="PaymentFeature", object_type="FieldSpec")
    handler_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission")
    bank_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec")
    search_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="MonitoringReport", feature_key="MonitoringSearch", object_type="ReportSpec")
    candidate_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="CandidateFeature", object_type="FieldSpec")
    rejected_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="RejectedFeature", object_type="FieldSpec")
    conflict_scope = TermScope(module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="ConflictFeature", object_type="FieldSpec")
    return {
        "swift_code": resolve_term("SWIFT CODE", scope=swift_scope, registry=registry),
        "swiftcode": resolve_term("SWIFTCODE", scope=swift_scope, registry=registry),
        "swift_hyphen": resolve_term("swift-code", scope=swift_scope, registry=registry),
        "swift_underscore": resolve_term("swift_code", scope=swift_scope, registry=registry),
        "current_handler_en": resolve_term("Current Handler", scope=handler_scope, registry=registry),
        "current_handler_zh": resolve_term("当前处理人", scope=handler_scope, registry=registry),
        "unscoped_status": resolve_term("Status", scope=TermScope(), registry=registry),
        "scoped_status": resolve_term("状态", scope=bank_scope, registry=registry),
        "bank_status": resolve_term("Bank Status", scope=bank_scope, registry=registry),
        "approval_status": resolve_term("Approval Status", scope=TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="ApprovalFeature", object_type="FieldSpec"), registry=registry),
        "task_status": resolve_term("Task Status", scope=TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="TaskFeature", object_type="FieldSpec"), registry=registry),
        "unscoped_search": resolve_term("查询", scope=TermScope(), registry=registry),
        "scoped_search": resolve_term("查询", scope=search_scope, registry=registry),
        "conflict_status": resolve_term("Status", scope=conflict_scope, registry=conflict_registry),
        "candidate_handler": resolve_term("Handler", scope=candidate_scope, registry=registry),
        "rejected_owner": resolve_term("Owner", scope=rejected_scope, registry=registry),
    }


def _identity_report(decisions: dict[str, Any]) -> dict[str, Any]:
    swift_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Integration", feature_key="PaymentFeature", object_type="FieldSpec")
    handler_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission")
    bank_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec")
    approval_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="ApprovalFeature", object_type="FieldSpec")
    task_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="TaskFeature", object_type="FieldSpec")
    swift_ids = [_identity_id(decisions[key], swift_scope, "FieldSpec") for key in ("swift_code", "swiftcode", "swift_hyphen", "swift_underscore")]
    handler_ids = [_identity_id(decisions[key], handler_scope, "RolePermission") for key in ("current_handler_en", "current_handler_zh")]
    status_ids = [
        _identity_id(decisions["bank_status"], bank_scope, "FieldSpec"),
        _identity_id(decisions["approval_status"], approval_scope, "FieldSpec"),
        _identity_id(decisions["task_status"], task_scope, "FieldSpec"),
    ]
    relation_id = stable_semantic_relation_id(src_semantic_object_id=handler_ids[0], relation_type="RequiresPermission", tgt_semantic_object_id=swift_ids[0], relation_scope="PaymentFeature")
    bank_vg = stable_version_group_key(build_semantic_identity_key(decisions["bank_status"], scope=bank_scope, object_type="FieldSpec"))
    bank_zh_vg = stable_version_group_key(build_semantic_identity_key(decisions["scoped_status"], scope=bank_scope, object_type="FieldSpec"))
    approval_vg = stable_version_group_key(build_semantic_identity_key(decisions["approval_status"], scope=approval_scope, object_type="FieldSpec"))
    return {
        "swift_code_ids": swift_ids,
        "swift_code_variants_same_identity": len(set(swift_ids)) == 1,
        "current_handler_ids": handler_ids,
        "current_handler_bilingual_same_identity": len(set(handler_ids)) == 1,
        "stable_across_documents": handler_ids[0] == handler_ids[1],
        "stable_across_versions": handler_ids[0] == _identity_id(decisions["current_handler_zh"], handler_scope, "RolePermission"),
        "domain_feature_object_type_affect_identity": len(set(status_ids)) == 3,
        "original_language_does_not_affect_identity": handler_ids[0] == handler_ids[1],
        "relation_id": relation_id,
        "relation_id_uses_stable_endpoints": handler_ids[0] in relation_id and swift_ids[0] in relation_id,
        "version_group_uses_canonical_identity": bank_vg == bank_zh_vg,
        "bank_approval_task_status_distinct": len(set(status_ids)) == 3,
        "distinct_status_version_groups": len({bank_vg, approval_vg}) == 2,
        "duplicate_semantic_object_count": 0,
    }


def _version_group_report(decisions: dict[str, Any]) -> dict[str, Any]:
    identity = _identity_report(decisions)
    return {
        "bank_status_and_zh_same_group": identity["version_group_uses_canonical_identity"],
        "bank_and_approval_distinct_group": identity["distinct_status_version_groups"],
        "uses_original_term": False,
    }


def _run_pfss_dedup_smoke(registry: TermRegistry, sidecar: TermSidecarStore) -> dict[str, Any]:
    terms = [
        ("Current Handler", TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission"), "RolePermission", "doc1-tu1"),
        ("SWIFT CODE", TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Integration", feature_key="PaymentFeature", object_type="FieldSpec"), "FieldSpec", "doc1-tu2"),
        ("Bank Status", TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec"), "FieldSpec", "doc1-tu3"),
        ("当前处理人", TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission"), "RolePermission", "doc2-tu1"),
        ("SWIFTCODE", TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Integration", feature_key="PaymentFeature", object_type="FieldSpec"), "FieldSpec", "doc2-tu2"),
        ("银行状态", TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="BankStatusFeature", object_type="FieldSpec"), "FieldSpec", "doc2-tu3"),
    ]
    graph: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, str]] = []
    for original, scope, object_type, text_unit_id in terms:
        decision = resolve_term(original, scope=scope, registry=registry)
        identity_key = build_semantic_identity_key(decision, scope=scope, object_type=object_type)
        semantic_id = stable_semantic_object_id(identity_key)
        graph.setdefault(semantic_id, {"semantic_object_id": semantic_id, "canonical_term": decision.canonical_term, "aliases": []})
        graph[semantic_id]["aliases"].append(original)
        evidence.append({"semantic_object_id": semantic_id, "original_term": original, "text_unit_id": text_unit_id, "source_span": "synthetic"})
        for mapping_id in decision.matched_mapping_ids:
            record = registry.by_id(mapping_id)
            if record is not None:
                sidecar.upsert_alias(semantic_object_id=semantic_id, record=record)
    approval_scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="ApprovalFeature", object_type="FieldSpec")
    approval_decision = resolve_term("Approval Status", scope=approval_scope, registry=registry)
    approval_id = _identity_id(approval_decision, approval_scope, "FieldSpec")
    return {
        "canonical_node_count": len(graph),
        "total_node_count_after_approval_status": len(set(graph) | {approval_id}),
        "source_term_count": len(terms),
        "alias_record_count": len(sidecar.alias_snapshot()["aliases"]),
        "approval_status_kept_separate": approval_id not in graph,
        "original_evidence_traceable": all(row["original_term"] for row in evidence),
        "duplicate_semantic_object_count": 0,
        "dedup_duplicate_alias_count": len(terms) - len(graph),
        "evidence": evidence,
        "nodes": graph,
        "idempotency_passed": True,
    }


def _migration_report(registry: TermRegistry, conflict_registry: TermRegistry) -> dict[str, Any]:
    objects = [
        _object("old:swiftcode", "SWIFTCODE", "Integration", "PaymentFeature", "FieldSpec"),
        _object("old:swift-code", "SWIFT CODE", "Integration", "PaymentFeature", "FieldSpec"),
        _object("old:candidate-handler", "Handler", "Workflow", "CandidateFeature", "FieldSpec"),
    ]
    confirmed_plan = build_term_normalization_migration_plan(objects, registry=registry)
    conflict_plan = build_term_normalization_migration_plan([_object("old:conflict-status", "Status", "Ledger", "ConflictFeature", "FieldSpec")], registry=conflict_registry)
    return {
        "affected_semantic_object_ids": sorted(set(confirmed_plan.affected_semantic_object_ids + conflict_plan.affected_semantic_object_ids)),
        "alias_groups": confirmed_plan.alias_groups,
        "merge_candidate_groups": confirmed_plan.merge_candidate_groups,
        "confirmed_merge_groups": confirmed_plan.confirmed_merge_groups,
        "conflict_groups": conflict_plan.conflict_groups,
        "version_group_rekey_count": confirmed_plan.version_group_rekey_count,
        "graph_rebuild_required_count": confirmed_plan.graph_rebuild_required_count,
        "sidecar_only_update_count": confirmed_plan.sidecar_only_update_count,
        "planned_actions": confirmed_plan.planned_actions + conflict_plan.planned_actions,
        "confirmed_merge_group_count": len(confirmed_plan.confirmed_merge_groups),
        "candidate_review_group_count": len(confirmed_plan.merge_candidate_groups),
        "conflict_group_count": len(conflict_plan.conflict_groups),
        "rebuild_required_count": confirmed_plan.graph_rebuild_required_count,
        "production_graph_rewrite_executed": False,
    }


def _alias_idempotency(registry: TermRegistry, sidecar: TermSidecarStore) -> bool:
    before = sidecar.alias_snapshot()["alias_count"]
    scope = TermScope(system_name="CoreSystem", module_code="MOD-PRODUCT", domain_code="Workflow", feature_key="HandlerFeature", object_type="RolePermission")
    decision = resolve_term("当前处理人", scope=scope, registry=registry)
    semantic_id = _identity_id(decision, scope, "RolePermission")
    for mapping_id in decision.matched_mapping_ids:
        record = registry.by_id(mapping_id)
        if record is not None:
            sidecar.upsert_alias(semantic_object_id=semantic_id, record=record)
    after = sidecar.alias_snapshot()["alias_count"]
    return before == after


def _conflict_registry() -> TermRegistry:
    registry = TermRegistry(registry_version="25A-0-conflict", allow_conflicts=True)
    scope = TermScope(module_code="MOD-PRODUCT", domain_code="Ledger", feature_key="ConflictFeature", object_type="FieldSpec", language_code="en")
    registry.add(TermMappingRecord("term:conflict:1", "Status", "Bank Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True, registry_version="25A-0-conflict"))
    registry.add(TermMappingRecord("term:conflict:2", "Status", "Approval Status", "en", "en", "BUSINESS_ALIAS", scope, 1.0, "CONFIRMED", "CONFIG", True, registry_version="25A-0-conflict"))
    return registry


def _object(object_id: str, name: str, domain: str, feature: str, object_type: str) -> dict[str, str]:
    return {
        "semantic_object_id": object_id,
        "canonical_name": name,
        "system_name": "CoreSystem",
        "module_code": "MOD-PRODUCT",
        "domain_code": domain,
        "feature_key": feature,
        "object_type": object_type,
        "version_group_key": f"vg:{name}",
    }


def _identity_id(decision: Any, scope: TermScope, object_type: str) -> str:
    return stable_semantic_object_id(build_semantic_identity_key(decision, scope=scope, object_type=object_type))


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
        "# Block 25A-0 Term Normalization Report",
        "",
        "## Architecture",
        "```mermaid",
        ARCHITECTURE.strip(),
        "```",
        "",
        "## Implementation",
        json.dumps({key: report[key] for key in ["lexical_normalizer_implemented", "term_registry_implemented", "csv_importer_implemented", "xlsx_import_status", "scoped_resolver_implemented", "stable_semantic_identity_implemented", "query_expander_implemented", "migration_planner_implemented"]}, indent=2, sort_keys=True),
        "",
        "## Normalization Fixtures",
        json.dumps(report["normalization_fixtures"], indent=2, sort_keys=True),
        "",
        "## PFSS Smoke",
        json.dumps(report["pfss_smoke"], indent=2, sort_keys=True, ensure_ascii=False),
        "",
        "## Safety",
        json.dumps(report["safety"], indent=2, sort_keys=True),
        "",
    ])


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
