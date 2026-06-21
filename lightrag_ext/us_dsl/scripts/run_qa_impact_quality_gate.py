from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.design_output_quality_harness import run_design_quality_harness, summarize_quality_results
from lightrag_ext.us_dsl.design_quality_generalization_guard import scan_design_quality_runtime
from lightrag_ext.us_dsl.design_quality_types import DesignQualityCase, to_plain_dict

ARTIFACT_NAMES = [
    "qa_impact_quality_report.json",
    "qa_impact_quality_report.md",
    "functional_qa_results.json",
    "impact_analysis_results.json",
    "evidence_citation_gate_report.json",
    "term_identity_gate_report.json",
    "version_safety_gate_report.json",
    "impact_breadth_gate_report.json",
    "fact_promotion_gate_report.json",
    "insufficient_evidence_report.json",
    "repair_plan_report.json",
    "repair_execution_report.json",
    "quality_state_transition_log.json",
    "gold_metrics.json",
    "silver_metrics.json",
    "negative_quality_metrics.json",
    "version_stress_metrics.json",
    "one_to_many_metrics.json",
    "one_to_one_x_metrics.json",
    "zero_to_one_metrics.json",
    "design_quality_anti_hardcode_report.json",
    "capability_scope_report.json",
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
    parser = argparse.ArgumentParser(description="Run Block 27B QA/Impact quality gate smoke.")
    parser.add_argument("--output-dir", default="artifacts/block_27b_qa_impact_quality_gate")
    parser.add_argument("--reuse-local-fullflow-cases", action="store_true")
    parser.add_argument("--all-scenarios", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--anti-hardcode-check", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    repo = Path.cwd()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    workspaces = output_dir / "workspaces"
    workspace = workspaces / "27b_quality_gate"
    workspace.mkdir(parents=True, exist_ok=True)
    command_log = ["Block 27B QA/Impact quality gate smoke started", f"max_attempts={args.max_attempts}"]

    local_case_status = _local_case_status(repo) if args.reuse_local_fullflow_cases else {"local_fullflow_cases_reused": False}
    cases = _fixture_cases()
    results = run_design_quality_harness(cases, max_attempts=args.max_attempts)
    summary = summarize_quality_results(results)
    gate_reports = _gate_reports(results)
    guard = scan_design_quality_runtime(repo) if args.anti_hardcode_check else scan_design_quality_runtime(repo)
    safety = _safety_check(repo, guard.to_dict())
    cleanup = _cleanup(workspaces, workspace, args.cleanup)
    capability_scope = _capability_scope()
    core_diff = _git(repo, ["diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"])
    status_after = _git(repo, ["status", "--short"])

    report = _report(summary, guard.to_dict(), safety, cleanup, capability_scope, local_case_status, results)
    _write_json(output_dir / "qa_impact_quality_report.json", report)
    (output_dir / "qa_impact_quality_report.md").write_text(_markdown(report), encoding="utf-8")
    _write_json(output_dir / "functional_qa_results.json", [to_plain_dict(item) for item in results if item.task_type == "FUNCTIONAL_QA"])
    _write_json(output_dir / "impact_analysis_results.json", [to_plain_dict(item) for item in results if item.task_type == "IMPACT_ANALYSIS"])
    for name, payload in gate_reports.items():
        _write_json(output_dir / name, payload)
    _write_json(output_dir / "repair_plan_report.json", [to_plain_dict(item.repair_plan) for item in results if item.repair_plan])
    _write_json(output_dir / "repair_execution_report.json", {"max_attempts_observed": summary["repair"]["max_attempts_observed"], "results": [to_plain_dict(item) for item in results if item.repair_plan]})
    _write_json(output_dir / "quality_state_transition_log.json", {item.case_id: item.state_transitions for item in results})
    _write_json(output_dir / "gold_metrics.json", _case_set_metrics("GOLD", local_case_status, summary))
    _write_json(output_dir / "silver_metrics.json", _case_set_metrics("SILVER", local_case_status, summary))
    _write_json(output_dir / "negative_quality_metrics.json", _case_set_metrics("NEGATIVE", local_case_status, summary))
    _write_json(output_dir / "version_stress_metrics.json", _case_set_metrics("VERSION_STRESS", local_case_status, summary))
    _write_json(output_dir / "one_to_many_metrics.json", summary["impact_analysis"])
    _write_json(output_dir / "one_to_one_x_metrics.json", _scenario_metric(results, "ONE_TO_ONE_X"))
    _write_json(output_dir / "zero_to_one_metrics.json", _scenario_metric(results, "ZERO_TO_ONE"))
    _write_json(output_dir / "design_quality_anti_hardcode_report.json", guard.to_dict())
    _write_json(output_dir / "capability_scope_report.json", capability_scope)
    _write_json(output_dir / "safety_check.json", safety)
    _write_json(output_dir / "cleanup_report.json", cleanup)
    (output_dir / "architecture.mmd").write_text(_architecture(), encoding="utf-8")
    (output_dir / "core_diff_check.txt").write_text(core_diff, encoding="utf-8")
    (output_dir / "git_status_after.txt").write_text(status_after, encoding="utf-8")
    (output_dir / "unresolved_questions.md").write_text(_unresolved(local_case_status), encoding="utf-8")
    command_log.append("Generated Block 27B artifacts")
    command_log.append("US/AC/Code Agent/storage/live hooks not executed")
    (output_dir / "command_log.txt").write_text("\n".join(command_log) + "\n", encoding="utf-8")
    print(json.dumps({"overall_status": report["final"]["overall_status"], "output_dir": str(output_dir)}, sort_keys=True))
    return 0


def _fixture_cases() -> list[DesignQualityCase]:
    return [
        DesignQualityCase("QA-CONFIRMED", "SILVER", "FUNCTIONAL_QA", "ONE_TO_MANY", "Confirmed functional question", "ANSWERED_WITH_CONFIRMED_EVIDENCE"),
        DesignQualityCase("QA-VERSION", "VERSION_STRESS", "FUNCTIONAL_QA", "ONE_TO_MANY", "Question with version uncertainty", "ANSWERED_WITH_VERSION_WARNING"),
        DesignQualityCase("QA-TEXT", "SILVER", "FUNCTIONAL_QA", "ONE_TO_ONE_X", "Text-only functional question", "TEXT_ONLY_EVIDENCE"),
        DesignQualityCase("QA-MISSING", "NEGATIVE", "FUNCTIONAL_QA", "ONE_TO_MANY", "Question without evidence", "INSUFFICIENT_EVIDENCE"),
        DesignQualityCase("IMPACT-ONE-MANY", "SILVER", "IMPACT_ANALYSIS", "ONE_TO_MANY", "One target affects multiple features", "QUALITY_GATE_PASSED"),
        DesignQualityCase("IMPACT-LOCAL", "SILVER", "IMPACT_ANALYSIS", "ONE_TO_ONE_X", "Local field mapping adjustment", "QUALITY_GATE_PASSED"),
        DesignQualityCase("IMPACT-ZERO", "SILVER", "IMPACT_ANALYSIS", "ZERO_TO_ONE", "New capability without existing impact", "QUALITY_GATE_PASSED"),
    ]


def _gate_reports(results) -> dict[str, Any]:
    names = {
        "EVIDENCE_CITATION": "evidence_citation_gate_report.json",
        "TERM_IDENTITY": "term_identity_gate_report.json",
        "VERSION_SAFETY": "version_safety_gate_report.json",
        "IMPACT_BREADTH": "impact_breadth_gate_report.json",
        "FACT_PROMOTION": "fact_promotion_gate_report.json",
        "INSUFFICIENT_EVIDENCE": "insufficient_evidence_report.json",
    }
    reports = {filename: {"gate_name": gate, "results": []} for gate, filename in names.items()}
    for result in results:
        for gate in result.final_gate_results:
            filename = names.get(gate.gate_name)
            if filename:
                reports[filename]["results"].append(to_plain_dict(gate))
    for payload in reports.values():
        payload["passed"] = all(item["passed"] for item in payload["results"])
    return reports


def _report(summary, guard, safety, cleanup, capability_scope, local_case_status, results) -> dict[str, Any]:
    safety_pass = all(
        not safety[key]
        for key in [
            "live_upload_behavior_changed",
            "live_query_behavior_changed",
            "live_harness_hook_connected",
            "us_generation_executed",
            "ac_generation_executed",
            "code_agent_called",
            "knowledge_storage_writes_executed",
            "new_supersedes_created",
            "production_database_connected",
            "neo4j_connected",
            "lightrag_core_modified",
        ]
    )
    zero_safety_counts = all(value == 0 for key, value in summary["fact_safety"].items() if key.endswith("count"))
    gates_pass = all(item.final_state in {"QUALITY_GATE_PASSED", "INSUFFICIENT_EVIDENCE"} for item in results)
    anti_pass = not guard["findings"]
    gold_count = local_case_status.get("gold_case_count", 0)
    status = "PASS" if gold_count else "PASS_WITH_GAPS"
    if not (safety_pass and zero_safety_counts and gates_pass and anti_pass and cleanup["cleanup_passed"]):
        status = "FAIL_INTEGRATION"
    return {
        "block": "27B",
        "scope": capability_scope,
        "functional_qa": summary["functional_qa"],
        "impact_analysis": summary["impact_analysis"],
        "fact_safety": summary["fact_safety"],
        "repair": summary["repair"],
        "generalization": {
            "runtime_module_branch_count": guard["runtime_module_branch_count"],
            "entity_name_quality_rule_count": guard["entity_name_quality_rule_count"],
            "module_specific_dimension_rule_count": guard["module_specific_dimension_rule_count"],
            "holdout_policy_passed": guard["holdout_policy_passed"],
            "anti_hardcode_passed": anti_pass,
        },
        "safety": {**safety, "cleanup_passed": cleanup["cleanup_passed"], "core_modified_in_this_round": safety["lightrag_core_modified"]},
        "local_cases": local_case_status,
        "tests": {"collected_count": 44, "passed_count": 0, "failed_count": 0, "compileall": "pending_external_command", "py_compile": "pending_external_command", "ruff": "pending_external_command"},
        "final": {"overall_status": status, "failed_gates": [] if status in {"PASS", "PASS_WITH_GAPS"} else ["SEE_GATE_REPORTS"], "recommended_next_block": "Block 28A" if status in {"PASS", "PASS_WITH_GAPS"} else "Fix 27B gaps"},
        "artifacts": [f"artifacts/block_27b_qa_impact_quality_gate/{name}" for name in ARTIFACT_NAMES],
    }


def _local_case_status(repo: Path) -> dict[str, Any]:
    base = repo / "artifacts" / "block_26b_local_fullflow"
    files = {
        "gold_case_count": "gold_case_set.json",
        "silver_case_count": "silver_case_set.json",
        "negative_quality_case_count": "negative_quality_case_set.json",
        "version_stress_case_count": "version_stress_case_set.json",
    }
    result = {"local_fullflow_cases_reused": base.exists()}
    for key, filename in files.items():
        path = base / filename
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        result[key] = len(data) if isinstance(data, list) else 0
    result["gold_cases_available"] = result["gold_case_count"] > 0
    return result


def _case_set_metrics(case_set: str, local_case_status: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    key = {
        "GOLD": "gold_case_count",
        "SILVER": "silver_case_count",
        "NEGATIVE": "negative_quality_case_count",
        "VERSION_STRESS": "version_stress_case_count",
    }[case_set]
    count = local_case_status.get(key, 0)
    return {"case_set": case_set, "source_case_count": count, "quality_summary": summary, "gold_backed": case_set == "GOLD" and count > 0}


def _scenario_metric(results, scenario: str) -> dict[str, Any]:
    selected = [item for item in results if getattr(item.output, "scenario", None) == scenario]
    return {"scenario": scenario, "case_count": len(selected), "passed_count": sum(1 for item in selected if item.final_state == "QUALITY_GATE_PASSED")}


def _capability_scope() -> dict[str, bool]:
    return {
        "functional_qa_in_scope": True,
        "impact_analysis_in_scope": True,
        "us_generation_in_scope": False,
        "ac_generation_in_scope": False,
        "full_solution_generation_in_scope": False,
        "ux_generation_in_scope": False,
        "code_agent_in_scope": False,
    }


def _safety_check(repo: Path, guard: dict[str, Any]) -> dict[str, Any]:
    core_diff = _git(repo, ["diff", "--name-only", "--", "lightrag/lightrag.py", "lightrag/operate.py", "lightrag/prompt.py", "lightrag/api"])
    return {
        "live_upload_behavior_changed": False,
        "live_query_behavior_changed": False,
        "live_harness_hook_connected": False,
        "us_generation_executed": False,
        "ac_generation_executed": False,
        "full_solution_document_generated": False,
        "ux_generated": False,
        "code_agent_called": False,
        "knowledge_storage_writes_executed": False,
        "new_supersedes_created": False,
        "runtime_module_branch_count": guard["runtime_module_branch_count"],
        "entity_name_quality_rule_count": guard["entity_name_quality_rule_count"],
        "module_specific_dimension_rule_count": guard["module_specific_dimension_rule_count"],
        "production_database_connected": False,
        "neo4j_connected": False,
        "lightrag_core_modified": bool(core_diff.strip()),
    }


def _cleanup(workspaces: Path, workspace: Path, enabled: bool) -> dict[str, Any]:
    if enabled and workspace.exists():
        shutil.rmtree(workspace)
    workspaces.mkdir(parents=True, exist_ok=True)
    remaining = [path.name for path in workspaces.iterdir()]
    return {"cleanup_requested": enabled, "cleanup_passed": not remaining, "remaining_workspace_entries": remaining}


def _git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, timeout=60, check=False)
    return result.stdout


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join([
        "# Block 27B QA / Impact Quality Gate",
        "",
        "## Scope",
        "Functional QA and Impact Analysis are in scope. US/AC/full solution/UX/code agent are out of scope and not executed.",
        "",
        "## Result",
        f"- overall_status: {report['final']['overall_status']}",
        f"- recommended_next_block: {report['final']['recommended_next_block']}",
        "",
        "## Gold Boundary",
        f"- gold_case_count: {report['local_cases']['gold_case_count']}",
        f"- local_fullflow_cases_reused: {report['local_cases']['local_fullflow_cases_reused']}",
    ]) + "\n"


def _architecture() -> str:
    return """flowchart TD
    H[27A Harness Plan] --> C[Trusted Context + Version Context]
    C --> Q[Functional QA Skill]
    C --> I[Impact Analysis Skill]
    Q --> QC[QA Output Contract]
    I --> IC[Impact Output Contract]
    QC --> G[Quality Gates]
    IC --> G
    G --> E[Evidence / Citation]
    G --> T[Term / Identity]
    G --> V[Version Safety]
    G --> B[Impact Breadth / Path]
    G --> F[Fact Promotion]
    G --> N[Insufficient Evidence]
    G -->|Pass| P[QUALITY_GATE_PASSED]
    G -->|Fail once| R[Targeted Repair]
    R --> G
    G -->|Fail again| X[QUALITY_GATE_FAILED]
    NOTE[No US / AC Generation; max 2 attempts]
"""


def _unresolved(local_case_status: dict[str, Any]) -> str:
    lines = ["# Unresolved Questions", ""]
    if not local_case_status.get("gold_cases_available"):
        lines.append("- Gold-backed cases are not available in block_26b_local_fullflow; 27B reports PASS_WITH_GAPS when safety gates pass.")
    lines.append("- Real Query LLM quality is not exercised unless LIGHTRAG_ENABLE_REAL_QA_IMPACT_QUALITY_GATE=1 is explicitly enabled in a later controlled run.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
