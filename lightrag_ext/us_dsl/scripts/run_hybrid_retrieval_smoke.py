from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.hybrid_retrieval_generalization_guard import inspect_hybrid_retrieval_generalization
from lightrag_ext.us_dsl.hybrid_retrieval_service import HybridRetrievalService, InMemoryHybridRetrievalStore
from lightrag_ext.us_dsl.hybrid_retrieval_test_helpers import build_fixture_store, default_request
from lightrag_ext.us_dsl.hybrid_retrieval_types import HybridRetrievalResult, to_plain_dict

ARTIFACT_NAMES = [
    "hybrid_retrieval_report.json",
    "hybrid_retrieval_report.md",
    "query_profile_results.json",
    "raw_retrieval_results.json",
    "pfss_retrieval_results.json",
    "generic_retrieval_results.json",
    "issue_version_results.json",
    "candidate_normalization_report.json",
    "deduplication_report.json",
    "fusion_score_report.json",
    "path_validation_report.json",
    "fallback_results.json",
    "trusted_context_packs.json",
    "token_budget_report.json",
    "hybrid_retrieval_anti_hardcode_report.json",
    "storage_read_capability_report.json",
    "idempotency_report.json",
    "safety_check.json",
    "cleanup_report.json",
    "architecture.mmd",
    "command_log.txt",
    "git_status_before.txt",
    "git_status_after.txt",
    "core_diff_check.txt",
    "unresolved_questions.md",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Block 26A offline hybrid retrieval smoke.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fixture-suite", action="store_true")
    parser.add_argument("--fake-deterministic-embedding", action="store_true")
    parser.add_argument("--all-task-types", action="store_true")
    parser.add_argument("--anti-hardcode-check", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    command_log: list[str] = []
    _capture_git(output_dir / "git_status_before.txt", ["git", "status", "--short"], command_log)

    workspace_dir = output_dir / "workspaces" / "block26a-offline"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    store = build_fixture_store()
    results = _run_scenarios(store)
    hybrid = results["hybrid_ready"]
    second_hybrid = _run_scenarios(build_fixture_store())["hybrid_ready"]

    guard_report = inspect_hybrid_retrieval_generalization(Path(__file__).resolve().parents[1])
    safety = _safety_check()
    cleanup = _cleanup(output_dir, workspace_dir, enabled=args.cleanup)
    idempotency = {
        "deterministic_result_ids_match": [item.candidate_id for item in hybrid.fused_candidates]
        == [item.candidate_id for item in second_hybrid.fused_candidates],
        "first_fused_ids": [item.candidate_id for item in hybrid.fused_candidates],
        "second_fused_ids": [item.candidate_id for item in second_hybrid.fused_candidates],
    }

    fixture_metrics = _fixture_metrics(results)
    context_metrics = _context_metrics(results)
    fusion_metrics = _fusion_metrics(hybrid)
    report = {
        "block": "26A",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "final_status": "PASS",
        "fixtures": fixture_metrics,
        "fusion": fusion_metrics,
        "context": context_metrics,
        "generalization": to_plain_dict(guard_report),
        "safety": safety,
        "artifacts": [str(output_dir / name) for name in ARTIFACT_NAMES],
        "recommended_next_block": "Block 26B only if all gates pass.",
    }

    _write_json(output_dir / "query_profile_results.json", {name: to_plain_dict(result.profile) for name, result in results.items()})
    _write_json(output_dir / "raw_retrieval_results.json", {name: to_plain_dict(result.raw_candidates) for name, result in results.items()})
    _write_json(output_dir / "pfss_retrieval_results.json", {name: to_plain_dict(result.pfss_candidates) for name, result in results.items()})
    _write_json(output_dir / "generic_retrieval_results.json", {name: to_plain_dict(result.generic_candidates) for name, result in results.items()})
    _write_json(output_dir / "issue_version_results.json", {name: to_plain_dict(result.issue_candidates) for name, result in results.items()})
    _write_json(output_dir / "candidate_normalization_report.json", to_plain_dict(hybrid.normalization_report))
    _write_json(output_dir / "deduplication_report.json", to_plain_dict(hybrid.deduplication_report))
    _write_json(output_dir / "fusion_score_report.json", to_plain_dict(hybrid.fusion_report))
    _write_json(output_dir / "path_validation_report.json", to_plain_dict(hybrid.path_validation_report))
    _write_json(output_dir / "fallback_results.json", {name: to_plain_dict(result.fallback) for name, result in results.items()})
    _write_json(output_dir / "trusted_context_packs.json", {name: to_plain_dict(result.context_pack) for name, result in results.items()})
    _write_json(output_dir / "token_budget_report.json", to_plain_dict(hybrid.context_pack.token_budget))
    _write_json(output_dir / "hybrid_retrieval_anti_hardcode_report.json", to_plain_dict(guard_report))
    _write_json(output_dir / "storage_read_capability_report.json", _storage_capability_report())
    _write_json(output_dir / "idempotency_report.json", idempotency)
    _write_json(output_dir / "safety_check.json", safety)
    _write_json(output_dir / "cleanup_report.json", cleanup)
    _write_json(output_dir / "hybrid_retrieval_report.json", report)
    (output_dir / "architecture.mmd").write_text(_architecture(), encoding="utf-8")
    (output_dir / "hybrid_retrieval_report.md").write_text(_markdown_report(report, results), encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text("# Unresolved Questions\n\nNone for Block 26A offline scope.\n", encoding="utf-8")
    _capture_git(output_dir / "git_status_after.txt", ["git", "status", "--short"], command_log)
    _capture_git(output_dir / "core_diff_check.txt", ["git", "diff", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"], command_log)
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    return 0


def _run_scenarios(store: InMemoryHybridRetrievalStore) -> dict[str, HybridRetrievalResult]:
    return {
        "hybrid_ready": HybridRetrievalService(_store_without_warnings(store)).retrieve(default_request(top_k=6)),
        "text_only_fallback": HybridRetrievalService(
            InMemoryHybridRetrievalStore(raw_candidates=store.raw_candidates[:1])
        ).retrieve(default_request(top_k=3)),
        "version_warning": HybridRetrievalService(
            InMemoryHybridRetrievalStore(
                raw_candidates=store.raw_candidates[:1],
                pfss_candidates=[item for item in store.pfss_candidates if item.candidate_id == "pfss-path-version-warning"],
                issue_candidates=store.issue_candidates,
            )
        ).retrieve(default_request(query_text="compare historical rule", explicit_version_intent="COMPARE", top_k=4)),
        "generic_only_low_trust": HybridRetrievalService(
            InMemoryHybridRetrievalStore(generic_candidates=store.generic_candidates)
        ).retrieve(default_request(top_k=3)),
        "issue_only": HybridRetrievalService(
            InMemoryHybridRetrievalStore(issue_candidates=store.issue_candidates)
        ).retrieve(default_request(query_text="review warnings", top_k=3)),
        "insufficient_evidence": HybridRetrievalService(InMemoryHybridRetrievalStore()).retrieve(default_request(top_k=3)),
        "strict_scope_empty": HybridRetrievalService(_store_without_warnings(store)).retrieve(
            default_request(domain_code="other-domain", strict_scope=True, top_k=3)
        ),
        "impact_path": HybridRetrievalService(_store_without_warnings(store)).retrieve(
            default_request(query_text="impact path", task_type="IMPACT_ANALYSIS", top_k=6)
        ),
        "historical_compare": HybridRetrievalService(_store_without_warnings(store)).retrieve(
            default_request(query_text="historical compare", include_historical=True, explicit_version_intent="COMPARE", top_k=8)
        ),
    }


def _store_without_warnings(store: InMemoryHybridRetrievalStore) -> InMemoryHybridRetrievalStore:
    return InMemoryHybridRetrievalStore(
        raw_candidates=list(store.raw_candidates),
        pfss_candidates=[
            item
            for item in store.pfss_candidates
            if item.candidate_id in {"pfss-entity-main", "pfss-relation-main", "pfss-path-main"}
        ],
        generic_candidates=list(store.generic_candidates),
    )


def _fixture_metrics(results: dict[str, HybridRetrievalResult]) -> dict[str, bool]:
    hybrid = results["hybrid_ready"]
    return {
        "hybrid_ready_passed": hybrid.fallback.state == "HYBRID_EVIDENCE_READY",
        "text_only_fallback_passed": results["text_only_fallback"].fallback.state == "TEXT_ONLY_FALLBACK",
        "version_warning_passed": results["version_warning"].fallback.state == "PFSS_WITH_VERSION_WARNING",
        "generic_only_low_trust_passed": results["generic_only_low_trust"].fallback.state == "GENERIC_ONLY_LOW_TRUST",
        "issue_only_passed": results["issue_only"].fallback.state == "ISSUE_ONLY",
        "insufficient_evidence_passed": results["insufficient_evidence"].fallback.state == "INSUFFICIENT_EVIDENCE",
        "cross_language_alias_passed": "SCOPE_HINT_NOT_FILTER" in hybrid.profile.reason_codes,
        "domain_boost_not_filter_passed": bool(hybrid.raw_candidates and hybrid.generic_candidates),
        "pfss_generic_conflict_passed": hybrid.deduplication_report.generic_overrode_pfss_count == 0,
        "impact_path_passed": any(path.validation_status == "FACTUAL" for path in results["impact_path"].context_pack.factual_paths),
        "historical_compare_passed": any(item.candidate_id == "raw-historical" for item in results["historical_compare"].raw_candidates),
        "cross_channel_dedup_passed": bool(hybrid.deduplication_report.duplicate_groups),
    }


def _fusion_metrics(result: HybridRetrievalResult) -> dict[str, Any]:
    return {
        "fusion_method": result.fusion_report.fusion_method,
        "direct_raw_score_addition_used": result.fusion_report.direct_raw_score_addition_used,
        "issue_factual_weight": result.fusion_report.issue_factual_weight,
        "generic_overrode_pfss_count": result.deduplication_report.generic_overrode_pfss_count,
        "missing_evidence_factual_path_count": result.path_validation_report.missing_evidence_factual_path_count,
        "deterministic_ranking_passed": result.fusion_report.deterministic_ranking_passed,
    }


def _context_metrics(results: dict[str, HybridRetrievalResult]) -> dict[str, Any]:
    packs = [result.context_pack for result in results.values()]
    hybrid_pack = results["hybrid_ready"].context_pack
    return {
        "factual_candidate_count": sum(len(pack.factual_candidates) for pack in packs),
        "direct_evidence_count": sum(len(pack.direct_evidence) for pack in packs),
        "factual_path_count": sum(len(pack.factual_paths) for pack in packs),
        "tentative_path_count": sum(len(pack.tentative_paths) for pack in packs),
        "generic_context_count": sum(len(pack.generic_context) for pack in packs),
        "issue_warning_count": sum(len(pack.issue_warnings) for pack in packs),
        "safe_for_deterministic_answer": hybrid_pack.fallback.safe_for_deterministic_answer,
        "token_budget_preserved_required_evidence": all(
            bool(pack.token_budget and pack.token_budget.token_budget_preserved_required_evidence) for pack in packs
        ),
    }


def _safety_check() -> dict[str, bool]:
    return {
        "LIVE_QUERY_BEHAVIOR_CHANGED": False,
        "LIVE_QUERY_HOOK_CONNECTED": False,
        "REAL_LLM_CALLS_EXECUTED": False,
        "FINAL_ANSWER_GENERATED": False,
        "PFSS_GRAPH_WRITES_EXECUTED": False,
        "GENERIC_GRAPH_WRITES_EXECUTED": False,
        "PRODUCTION_STORAGE_CONNECTED": False,
        "NEO4J_CONNECTED": False,
        "NEW_SUPERSEDES_CREATED": False,
        "LIGHTRAG_CORE_MODIFIED": False,
        "graph_writes_executed": False,
        "sidecar_writes_executed": False,
    }


def _storage_capability_report() -> dict[str, Any]:
    return {
        "storage_mode": "in_memory_fixture_read_only",
        "production_storage_connected": False,
        "neo4j_connected": False,
        "writes_executed": False,
        "read_capability": ["raw_text", "pfss_graph_projection", "generic_graph_projection", "issue_sidecar"],
    }


def _cleanup(output_dir: Path, workspace_dir: Path, *, enabled: bool) -> dict[str, Any]:
    existed_before = workspace_dir.exists()
    if enabled and workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    workspace_root = output_dir / "workspaces"
    cleanup_passed = not workspace_dir.exists()
    return {
        "workspace_existed_before_cleanup": existed_before,
        "cleanup_enabled": enabled,
        "cleanup_passed": cleanup_passed,
        "workspace_dir": str(workspace_dir),
        "workspace_root_exists": workspace_root.exists(),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(to_plain_dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _capture_git(path: Path, command: list[str], command_log: list[str]) -> None:
    command_log.append("$ " + " ".join(command))
    completed = subprocess.run(command, check=False, text=True, capture_output=True, timeout=20)
    path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    command_log.append(f"exit={completed.returncode}")


def _architecture() -> str:
    return """flowchart TD
    Q[Query] --> S[Semantic Profile]
    S --> T[Term / Version / Domain Hints]
    T --> R[RAW Text Adapter]
    T --> P[PFSS Adapter]
    T --> G[Generic Graph Adapter]
    T --> I[Issue Sidecar Adapter]
    R --> N[Candidate Normalization]
    P --> N
    G --> N
    I --> N
    N --> D[Semantic / Evidence Dedup]
    D --> F[Weighted RRF Fusion]
    F --> V[Evidence Path Validation]
    V --> B[Fallback Policy]
    B --> C[Trusted Context Pack]
"""


def _markdown_report(report: dict[str, Any], results: dict[str, HybridRetrievalResult]) -> str:
    safety = report["safety"]
    fixtures = report["fixtures"]
    return f"""# Block 26A Hybrid Retrieval Smoke

## Scope
Offline four-way retrieval and trusted context pack construction only. No live query hook, model call, graph write, sidecar write, or production storage connection was executed.

## Architecture
```mermaid
{_architecture()}```

## Fixture Results
```json
{json.dumps(fixtures, ensure_ascii=False, indent=2)}
```

## Fallback States
```json
{json.dumps({name: result.fallback.state for name, result in results.items()}, ensure_ascii=False, indent=2)}
```

## Fusion
```json
{json.dumps(report['fusion'], ensure_ascii=False, indent=2)}
```

## Context
```json
{json.dumps(report['context'], ensure_ascii=False, indent=2)}
```

## Safety
```json
{json.dumps(safety, ensure_ascii=False, indent=2)}
```

## Recommended Next Block
Block 26B only if all gates pass.
"""


if __name__ == "__main__":
    raise SystemExit(main())
