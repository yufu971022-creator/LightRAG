from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .dsl_knowledge_ingestion import (
    DslKnowledgeIngestionConfig,
    run_dsl_knowledge_ingestion,
    serialize_dsl_knowledge_ingestion_report,
)
from .dsl_knowledge_ingestion_readiness import build_readiness_artifacts
from .graph_retrieval_eval import (
    build_graph_retrieval_evaluation_report,
    serialize_graph_retrieval_evaluation_report,
)
from .kg_real_graph_smoke import SMOKE_GRAPH_STORAGE
from .lc_business_qa_eval import (
    run_lc_business_qa_ab_eval,
    serialize_lc_business_qa_ab_eval_report,
)
from .lc_impact_analysis_eval import (
    run_lc_impact_analysis_ab_eval,
    serialize_impact_analysis_ab_eval_report,
)
from .lc_mini_graph_smoke import (
    EXPECTED_FIRST_US_ID,
    EXPECTED_LAST_US_ID,
    EXPECTED_SOURCE_TEXT_UNIT_COUNT,
    LcMiniGraphSmokeConfig,
    build_lc_mini_build_result,
)
from .lc_us_generation_eval import (
    run_lc_us_generation_ab_eval,
    serialize_us_generation_ab_eval_report,
)


DEFAULT_LC_US_FILE = Path("/Users/hufaofao/Projects/LC_Acceptable_Bank_US_v1.md")
FIXTURE_LC_US_FILE = Path("lightrag_ext/us_dsl/tests/fixtures/LC_Acceptable_Bank_US_v1.md")
DEFAULT_OUTPUT_DIR = Path("/Users/hufaofao/Projects/测试结果")
EXPECTED_US_COUNT = 66
NAMESPACE = "dsl_test_lc_66us_effect"


REPORT_DIRS = [
    "00_input_check",
    "01_ingestion",
    "02_graph_retrieval",
    "03_business_qa",
    "04_us_generation",
    "05_impact_analysis",
    "06_issue_summary",
    "07_logs",
    "08_artifacts",
    "test_graph_workspace",
]


@dataclass
class Lc66UsEffectTestResult:
    output_dir: str
    input_file: str | None
    namespace: str
    working_dir: str
    source_us_count: int = 0
    source_text_unit_count: int = 0
    graph_write_succeeded: bool = False
    custom_kg_chunk_count: int = 0
    custom_kg_entity_count: int = 0
    custom_kg_relationship_count: int = 0
    retrieval_improved_count: int = 0
    retrieval_degraded_count: int = 0
    business_qa_improved_count: int = 0
    business_qa_degraded_count: int = 0
    us_generation_improved_count: int = 0
    us_generation_degraded_count: int = 0
    impact_analysis_improved_count: int = 0
    impact_analysis_degraded_count: int = 0
    unsupported_claim_count: int = 0
    invalid_citation_count: int = 0
    version_review_required_count: int = 0
    optimization_backlog_count: int = 0
    readme_path: str = ""
    neo4j_connected: bool = False
    production_write: bool = False
    real_llm_called: bool = False
    lightrag_core_modified: bool = False
    recommended_next_step: str = ""
    report_files: list[str] = field(default_factory=list)


def run_lc_66us_e2e_effect_test(
    *,
    lc_us_file: str | Path | None = None,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    namespace: str = NAMESPACE,
    working_dir: str | Path | None = None,
    mode: str = "offline",
) -> Lc66UsEffectTestResult:
    output_root = Path(output_dir).expanduser().resolve()
    workspace = Path(working_dir).expanduser().resolve() if working_dir else output_root / "test_graph_workspace"
    _ensure_output_dirs(output_root)
    log_lines: list[str] = []
    report_files: list[str] = []
    started = time.time()

    source_file = _resolve_lc_source(lc_us_file)
    if source_file is None:
        error = {
            "status": "FAIL",
            "reason": "LC_INPUT_FILE_NOT_FOUND",
            "checked_paths": [
                str(Path(lc_us_file).expanduser()) if lc_us_file else str(DEFAULT_LC_US_FILE),
                str(FIXTURE_LC_US_FILE),
            ],
        }
        _write_json(output_root / "00_input_check" / "input_error.json", error)
        _write_text(output_root / "00_input_check" / "input_check.md", _markdown_kv("Input Check", error))
        return Lc66UsEffectTestResult(
            output_dir=str(output_root),
            input_file=None,
            namespace=namespace,
            working_dir=str(workspace),
            recommended_next_step="FIX_INPUT_FILE",
            report_files=[str(output_root / "00_input_check" / "input_error.json")],
        )

    input_check = _build_input_check(source_file)
    report_files.extend(
        _write_pair(
            output_root / "00_input_check",
            "input_check",
            input_check,
            title="Input Check",
        )
    )
    if input_check["status"] != "PASS":
        _write_run_log(output_root, log_lines, started)
        return Lc66UsEffectTestResult(
            output_dir=str(output_root),
            input_file=str(source_file),
            namespace=namespace,
            working_dir=str(workspace),
            source_us_count=int(input_check.get("source_us_count") or 0),
            source_text_unit_count=int(input_check.get("source_text_unit_count") or 0),
            recommended_next_step="FIX_INPUT_FILE",
            report_files=report_files,
        )

    _clear_workspace_if_safe(workspace, output_root)
    ingestion_config = DslKnowledgeIngestionConfig(
        enabled=True,
        source_path=str(source_file),
        module_name="LCAB",
        namespace=namespace,
        ingest_mode="module",
        target_graph_type="test_graph",
        test_namespace_only=True,
        allow_production=False,
        allow_neo4j=False,
        use_temp_working_dir=False,
        working_dir=str(workspace),
        force_local_graph_storage=True,
        isolate_remote_graph_env=True,
        use_fake_embedding=True,
        use_fake_llm=True,
        explicit_local_tokenizer=True,
        module_max_chunks=2000,
        module_max_entities=5000,
        module_max_relationships=5000,
        batch_size=100,
        cleanup_after_run=False,
        rollback_after_run=False,
    )
    log_lines.append("RUN module-level test graph ingestion")
    ingestion_report = run_dsl_knowledge_ingestion(
        source_path=str(source_file),
        module_name="LCAB",
        config=ingestion_config,
    )
    ingestion_data = serialize_dsl_knowledge_ingestion_report(ingestion_report)
    report_files.extend(
        _write_pair(
            output_root / "01_ingestion",
            "ingestion_report",
            ingestion_data,
            title="Module-level Test Graph Ingestion",
        )
    )

    payload, prepared, _readiness = build_readiness_artifacts(
        config=ingestion_config,
        source_path=str(source_file),
        module_name="LCAB",
    )
    custom_summary = {
        "chunk_count": len(prepared.custom_kg_input.get("chunks", [])),
        "entity_count": len(prepared.custom_kg_input.get("entities", [])),
        "relationship_count": len(prepared.custom_kg_input.get("relationships", [])),
        "endpoint_closure_passed": prepared.endpoint_closure_passed,
        "dangling_relationship_count": prepared.dangling_relationship_count,
        "forbidden_relation_count": prepared.forbidden_relation_count,
        "idempotency_key_duplicate_count": prepared.idempotency_key_duplicate_count,
    }
    sidecar_summary = {
        "sidecar_record_count": len(prepared.sidecar_records),
        "sidecar_alignment_passed": prepared.sidecar_alignment_passed,
        "rollback_plan_present": prepared.rollback_plan_present,
        "rollback_key_count": prepared.rollback_key_count,
        "rollback_strategy": prepared.rollback_strategy,
    }
    report_files.append(str(_write_json(output_root / "01_ingestion" / "custom_kg_summary.json", custom_summary)))
    report_files.append(str(_write_json(output_root / "01_ingestion" / "sidecar_summary.json", sidecar_summary)))
    report_files.append(str(_write_json(output_root / "01_ingestion" / "domain_distribution.json", ingestion_data["domain_distribution"])))
    report_files.append(str(_write_json(output_root / "01_ingestion" / "block_reason_distribution.json", ingestion_data["block_reason_distribution"])))

    if not _ingestion_passed(ingestion_report):
        final_summary, backlog = _build_issue_outputs(
            ingestion_data=ingestion_data,
            retrieval_summary={},
            business_summary={},
            us_summary={},
            impact_summary={},
            business_report=None,
            us_report=None,
            impact_report=None,
        )
        report_files.extend(_write_issue_outputs(output_root, final_summary, backlog))
        readme_path = _write_readme(output_root, source_file, namespace, workspace, ingestion_data, {}, {}, {}, {}, final_summary, backlog)
        report_files.append(str(readme_path))
        _write_run_manifest(output_root, source_file, workspace, namespace, report_files, started)
        _write_run_log(output_root, log_lines, started)
        return _result_from_outputs(
            output_root,
            source_file,
            namespace,
            workspace,
            ingestion_data,
            {},
            {},
            {},
            {},
            final_summary,
            backlog,
            readme_path,
            report_files,
        )

    retrieval_report = build_graph_retrieval_evaluation_report(
        source="LC_Acceptable_Bank_US_v1",
        payload=payload,
        sidecar_records=prepared.sidecar_records,
        max_queries=8,
    )
    retrieval_data = serialize_graph_retrieval_evaluation_report(retrieval_report)
    retrieval_summary = _retrieval_summary(retrieval_data)
    report_files.extend(
        _write_pair(output_root / "02_graph_retrieval", "retrieval_eval_report", retrieval_summary, title="Graph Retrieval A/B")
    )
    report_files.append(str(_write_json(output_root / "02_graph_retrieval" / "retrieval_case_results.json", retrieval_data.get("comparison_results", []))))

    business_report = run_lc_business_qa_ab_eval(
        mode=mode,
        max_cases=10,
        use_expanded_subset=True,
    )
    business_data = serialize_lc_business_qa_ab_eval_report(business_report)
    business_summary = _business_qa_summary(business_data)
    report_files.extend(
        _write_pair(output_root / "03_business_qa", "business_qa_eval_report", business_summary, title="Business QA A/B")
    )
    report_files.append(str(_write_json(output_root / "03_business_qa" / "business_qa_case_results.json", business_data.get("case_results", []))))

    us_report = run_lc_us_generation_ab_eval(
        mode=mode,
        max_cases=8,
        use_expanded_subset=True,
    )
    us_data = serialize_us_generation_ab_eval_report(us_report)
    us_summary = _us_generation_summary(us_data)
    report_files.extend(
        _write_pair(output_root / "04_us_generation", "us_generation_eval_report", us_summary, title="US Generation A/B")
    )
    report_files.append(str(_write_json(output_root / "04_us_generation" / "us_generation_case_results.json", us_data.get("case_results", []))))
    report_files.append(str(_write_text(output_root / "04_us_generation" / "generated_us_samples.md", _generated_us_samples(us_data))))

    impact_report = run_lc_impact_analysis_ab_eval(
        mode=mode,
        max_cases=6,
        use_expanded_subset=True,
    )
    impact_data = serialize_impact_analysis_ab_eval_report(impact_report)
    impact_summary = _impact_analysis_summary(impact_data)
    report_files.extend(
        _write_pair(output_root / "05_impact_analysis", "impact_analysis_eval_report", impact_summary, title="Impact Analysis A/B")
    )
    report_files.append(str(_write_json(output_root / "05_impact_analysis" / "impact_analysis_case_results.json", impact_data.get("case_results", []))))
    report_files.append(str(_write_text(output_root / "05_impact_analysis" / "impact_analysis_samples.md", _impact_samples(impact_data))))

    final_summary, backlog = _build_issue_outputs(
        ingestion_data=ingestion_data,
        retrieval_summary=retrieval_summary,
        business_summary=business_summary,
        us_summary=us_summary,
        impact_summary=impact_summary,
        business_report=business_data,
        us_report=us_data,
        impact_report=impact_data,
    )
    report_files.extend(_write_issue_outputs(output_root, final_summary, backlog))
    readme_path = _write_readme(
        output_root,
        source_file,
        namespace,
        workspace,
        ingestion_data,
        retrieval_summary,
        business_summary,
        us_summary,
        impact_summary,
        final_summary,
        backlog,
    )
    report_files.append(str(readme_path))
    manifest_path = _write_run_manifest(output_root, source_file, workspace, namespace, report_files, started)
    report_files.append(str(manifest_path))
    _write_run_log(output_root, log_lines, started)

    return _result_from_outputs(
        output_root,
        source_file,
        namespace,
        workspace,
        ingestion_data,
        retrieval_summary,
        business_summary,
        us_summary,
        impact_summary,
        final_summary,
        backlog,
        readme_path,
        report_files,
    )


def serialize_lc_66us_effect_test_result(result: Lc66UsEffectTestResult) -> dict[str, Any]:
    return asdict(result)


def _resolve_lc_source(lc_us_file: str | Path | None) -> Path | None:
    requested = Path(lc_us_file).expanduser() if lc_us_file else DEFAULT_LC_US_FILE
    if requested.exists():
        return requested.resolve()
    fixture = FIXTURE_LC_US_FILE
    if fixture.exists():
        return fixture.resolve()
    return None


def _build_input_check(source_file: Path) -> dict[str, Any]:
    try:
        build_result = build_lc_mini_build_result(
            LcMiniGraphSmokeConfig(
                lc_file_path=str(source_file),
                max_chunks=2000,
                max_entities=5000,
                max_relationships=5000,
            )
        )
        checks = {
            "file_exists": source_file.exists(),
            "source_us_count": build_result.source_us_count,
            "first_us_id": build_result.first_us_id,
            "last_us_id": build_result.last_us_id,
            "source_text_unit_count": build_result.source_text_unit_count,
            "unknown_section_count": build_result.unknown_section_count,
            "unknown_section_ratio": (
                build_result.unknown_section_count / build_result.source_text_unit_count
                if build_result.source_text_unit_count
                else 0.0
            ),
            "risks": list(build_result.risks),
        }
    except Exception as exc:
        return {
            "status": "FAIL",
            "input_file": str(source_file),
            "error": f"{type(exc).__name__}: {exc}",
        }
    issues = []
    if checks["source_us_count"] != EXPECTED_US_COUNT:
        issues.append("US_COUNT_MISMATCH")
    if checks["first_us_id"] != EXPECTED_FIRST_US_ID:
        issues.append("FIRST_US_ID_MISMATCH")
    if checks["last_us_id"] != EXPECTED_LAST_US_ID:
        issues.append("LAST_US_ID_MISMATCH")
    if checks["source_text_unit_count"] != EXPECTED_SOURCE_TEXT_UNIT_COUNT:
        issues.append("SOURCE_TEXT_UNIT_COUNT_WARN")
    if checks["unknown_section_count"]:
        issues.append("UNKNOWN_SECTION_WARN")
    return {
        "status": "PASS" if not [i for i in issues if not i.endswith("_WARN")] else "FAIL",
        "input_file": str(source_file),
        "expected_us_count": EXPECTED_US_COUNT,
        "expected_first_us_id": EXPECTED_FIRST_US_ID,
        "expected_last_us_id": EXPECTED_LAST_US_ID,
        "expected_source_text_unit_count": EXPECTED_SOURCE_TEXT_UNIT_COUNT,
        "issues": issues,
        **checks,
    }


def _ingestion_passed(report: Any) -> bool:
    return (
        bool(report.ready_to_write)
        and bool(report.canary_prerequisite_passed)
        and bool(report.ainsert_custom_kg_called)
        and bool(report.graph_write_succeeded)
        and not bool(report.neo4j_connected)
        and not bool(report.production_write)
        and bool(report.sidecar_alignment_passed)
        and bool(report.endpoint_closure_passed)
        and int(report.dangling_relationship_count) == 0
        and int(report.forbidden_relation_count) == 0
        and int(report.idempotency_key_duplicate_count) == 0
    )


def _retrieval_summary(data: dict[str, Any]) -> dict[str, Any]:
    comparisons = list(data.get("comparison_results") or [])
    graph_hit_missing_evidence_count = 0
    false_positive_count = 0
    for item in comparisons:
        graph_result = item.get("graph_aware_result") or {}
        graph_hit_missing_evidence_count += sum(
            1
            for issue in graph_result.get("issues", [])
            if issue.get("code") == "GRAPH_HIT_MISSING_EVIDENCE"
        )
        false_positive_count += int(graph_result.get("unsupported_claim_risk") or 0)
    return {
        "query_count": data.get("query_count", 0),
        "improved_count": data.get("improved_count", 0),
        "same_count": data.get("same_count", 0),
        "degraded_count": data.get("degraded_count", 0),
        "inconclusive_count": data.get("inconclusive_count", 0),
        "avg_entity_recall_delta": data.get("avg_entity_recall_delta", 0.0),
        "avg_relation_recall_delta": data.get("avg_relation_recall_delta", 0.0),
        "avg_evidence_coverage_delta": data.get("avg_evidence_coverage_delta", 0.0),
        "avg_source_span_coverage_delta": data.get("avg_source_span_coverage_delta", 0.0),
        "avg_graph_path_delta": data.get("avg_graph_path_delta", 0.0),
        "graph_hit_missing_evidence_count": graph_hit_missing_evidence_count,
        "false_positive_count": false_positive_count,
        "recommended_next_step": data.get("recommended_next_step", ""),
    }


def _business_qa_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_count": data.get("case_count", 0),
        "text_only_pass_count": data.get("text_only_pass_count", 0),
        "graph_aware_pass_count": data.get("graph_aware_pass_count", 0),
        "improved_count": data.get("improved_count", 0),
        "same_count": data.get("same_count", 0),
        "degraded_count": data.get("degraded_count", 0),
        "inconclusive_count": data.get("inconclusive_count", 0),
        "avg_text_score": data.get("avg_text_score", 0.0),
        "avg_graph_score": data.get("avg_graph_score", 0.0),
        "avg_score_delta": data.get("avg_score_delta", 0.0),
        "avg_evidence_grounding_delta": data.get("avg_evidence_grounding_delta", 0.0),
        "avg_source_span_delta": data.get("avg_source_span_delta", 0.0),
        "avg_unsupported_claim_delta": data.get("avg_unsupported_claim_delta", 0.0),
        "graph_path_used_count": data.get("graph_path_used_count", 0),
        "invalid_citation_count": data.get("cases_with_invalid_citation", 0),
        "candidate_as_confirmed_count": data.get("cases_with_candidate_as_confirmed", 0),
        "info_only_as_fact_count": _info_only_as_fact_count(data),
        "recommended_next_step": data.get("recommended_next_step", ""),
    }


def _us_generation_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_count": data.get("case_count", 0),
        "text_only_pass_count": data.get("text_only_pass_count", 0),
        "graph_aware_pass_count": data.get("graph_aware_pass_count", 0),
        "improved_count": data.get("improved_count", 0),
        "same_count": data.get("same_count", 0),
        "degraded_count": data.get("degraded_count", 0),
        "inconclusive_count": data.get("inconclusive_count", 0),
        "avg_text_score": data.get("avg_text_score", 0.0),
        "avg_graph_score": data.get("avg_graph_score", 0.0),
        "avg_score_delta": data.get("avg_score_delta", 0.0),
        "avg_evidence_grounding_delta": data.get("avg_evidence_grounding_delta", 0.0),
        "avg_source_span_delta": data.get("avg_source_span_delta", 0.0),
        "avg_unsupported_claim_delta": data.get("avg_unsupported_claim_delta", 0.0),
        "avg_structure_completeness_delta": data.get("avg_structure_completeness_delta", 0.0),
        "avg_business_rule_coverage_delta": data.get("avg_business_rule_coverage_delta", 0.0),
        "avg_review_readiness_delta": data.get("avg_review_readiness_delta", 0.0),
        "graph_path_used_count": data.get("graph_path_used_count", 0),
        "accept_as_is_count": data.get("accept_as_is_count", 0),
        "accept_with_minor_edits_count": data.get("accept_with_minor_edits_count", 0),
        "need_major_revision_count": data.get("need_major_revision_count", 0),
        "reject_count": data.get("reject_count", 0),
        "version_uncertain_case_result": _case_result_label(data, "LC-USGEN-008"),
        "recommended_next_step": data.get("recommended_next_step", ""),
    }


def _impact_analysis_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_count": data.get("case_count", 0),
        "text_only_pass_count": data.get("text_only_pass_count", 0),
        "graph_aware_pass_count": data.get("graph_aware_pass_count", 0),
        "improved_count": data.get("improved_count", 0),
        "same_count": data.get("same_count", 0),
        "degraded_count": data.get("degraded_count", 0),
        "inconclusive_count": data.get("inconclusive_count", 0),
        "avg_text_score": data.get("avg_text_score", 0.0),
        "avg_graph_score": data.get("avg_graph_score", 0.0),
        "avg_score_delta": data.get("avg_score_delta", 0.0),
        "avg_impact_dimension_delta": data.get("avg_impact_completeness_delta", 0.0),
        "avg_direct_impact_delta": data.get("avg_impact_completeness_delta", 0.0),
        "avg_indirect_impact_delta": data.get("avg_relation_path_delta", 0.0),
        "avg_evidence_grounding_delta": data.get("avg_evidence_grounding_delta", 0.0),
        "avg_source_span_delta": data.get("avg_source_span_delta", 0.0),
        "avg_unsupported_claim_delta": data.get("avg_unsupported_claim_delta", 0.0),
        "avg_false_positive_delta": 0.0,
        "avg_version_handling_delta": 0.0,
        "graph_path_used_count": data.get("graph_path_used_count", 0),
        "accept_as_is_count": _judgement_count(data, "PASS"),
        "accept_with_minor_edits_count": _judgement_count(data, "WARN"),
        "need_major_revision_count": 0,
        "reject_count": _judgement_count(data, "FAIL"),
        "recommended_next_step": data.get("recommended_next_step", ""),
    }


def _build_issue_outputs(
    *,
    ingestion_data: dict[str, Any],
    retrieval_summary: dict[str, Any],
    business_summary: dict[str, Any],
    us_summary: dict[str, Any],
    impact_summary: dict[str, Any],
    business_report: dict[str, Any] | None,
    us_report: dict[str, Any] | None,
    impact_report: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    unsupported_claim_count = (
        _unsupported_claims(business_report)
        + _unsupported_claims(us_report)
        + _unsupported_claims(impact_report)
    )
    invalid_citation_count = (
        _invalid_citations(business_report)
        + _invalid_citations(us_report)
        + _invalid_citations(impact_report)
    )
    issue_summary = {
        "unsupported_claim_count": unsupported_claim_count,
        "invalid_citation_count": invalid_citation_count,
        "candidate_as_confirmed_count": (
            _candidate_as_confirmed(business_report)
            + _candidate_as_confirmed(us_report)
            + _candidate_as_confirmed(impact_report)
        ),
        "info_only_as_fact_count": (
            _info_only_as_fact_count(business_report or {})
            + _info_only_as_fact_count(us_report or {})
            + _info_only_as_fact_count(impact_report or {})
        ),
        "missing_evidence_count": int(ingestion_data.get("evidence_missing_count") or 0),
        "version_review_required_count": int(ingestion_data.get("version_review_required_blocked_count") or 0),
        "forbidden_relation_count": int(ingestion_data.get("forbidden_relation_count") or 0),
        "dangling_relationship_count": int(ingestion_data.get("dangling_relationship_count") or 0),
        "sidecar_mismatch_count": 0 if ingestion_data.get("sidecar_alignment_passed") else 1,
        "graph_write_failure_count": 0 if ingestion_data.get("graph_write_succeeded") else 1,
        "retrieval_degraded_count": int((retrieval_summary or {}).get("degraded_count") or 0),
        "qa_degraded_count": int((business_summary or {}).get("degraded_count") or 0),
        "us_generation_degraded_count": int((us_summary or {}).get("degraded_count") or 0),
        "impact_analysis_degraded_count": int((impact_summary or {}).get("degraded_count") or 0),
        "source_span_missing_count": _source_span_missing(business_report) + _source_span_missing(us_report) + _source_span_missing(impact_report),
        "evidence_missing_count": int(ingestion_data.get("evidence_missing_count") or 0),
        "version_uncertain_count": int(ingestion_data.get("version_review_required_blocked_count") or 0),
        "relation_path_noise_count": int((retrieval_summary or {}).get("false_positive_count") or 0),
        "false_positive_count": int((retrieval_summary or {}).get("false_positive_count") or 0),
    }
    issue_summary["recommended_next_step"] = _final_next_step(issue_summary)
    return issue_summary, _optimization_backlog(issue_summary, ingestion_data)


def _optimization_backlog(
    issue_summary: dict[str, Any],
    ingestion_data: dict[str, Any],
) -> list[dict[str, Any]]:
    backlog: list[dict[str, Any]] = []
    if issue_summary["graph_write_failure_count"]:
        backlog.append(_backlog("GRAPH_WRITE_FAILURE", "HIGH", "Module-level test graph write failed.", "Fix custom_kg/governance/write isolation.", "FIX_MODULE_LEVEL_INGESTION"))
    if issue_summary["unsupported_claim_count"]:
        backlog.append(_backlog("GROUNDING", "HIGH", "Unsupported claims were detected.", "Tighten grounding and open-question handling.", "FIX_GROUNDING"))
    if issue_summary["invalid_citation_count"]:
        backlog.append(_backlog("EVIDENCE_CITATION", "HIGH", "Invalid citations were detected.", "Repair evidence id/source span citation mapping.", "FIX_EVIDENCE_CITATION"))
    degraded_count = sum(
        issue_summary[key]
        for key in [
            "retrieval_degraded_count",
            "qa_degraded_count",
            "us_generation_degraded_count",
            "impact_analysis_degraded_count",
        ]
    )
    if degraded_count:
        backlog.append(_backlog("GRAPH_AWARE_DEGRADED", "MEDIUM", "At least one graph-aware evaluation degraded.", "Tune retrieval/path filtering and scoring.", "TUNE_GRAPH_AWARE_EVAL"))
    if issue_summary["version_review_required_count"]:
        backlog.append(
            {
                **_backlog("VERSION_REVIEW_REQUIRED", "MEDIUM", "Version-related objects remain blocked by policy.", "Add explicit current/supersedes evidence or reviewer workflow.", "TUNE_VERSION_RELATION_POLICY"),
                "affected_domains": list((ingestion_data.get("domain_distribution") or {}).keys()),
            }
        )
    if not backlog:
        backlog.append(_backlog("USER_EFFECT_REVIEW", "LOW", "Offline test graph run is stable.", "Review saved reports and run user effect tests on retained test graph.", "READY_FOR_USER_EFFECT_REVIEW"))
    return backlog


def _backlog(
    issue_type: str,
    severity: str,
    description: str,
    recommended_fix: str,
    next_block_hint: str,
) -> dict[str, Any]:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "description": description,
        "affected_cases": [],
        "affected_domains": [],
        "affected_source_us_ids": [],
        "recommended_fix": recommended_fix,
        "next_block_hint": next_block_hint,
    }


def _final_next_step(issue_summary: dict[str, Any]) -> str:
    if issue_summary["graph_write_failure_count"]:
        return "FIX_MODULE_LEVEL_INGESTION"
    degraded_count = sum(
        issue_summary[key]
        for key in [
            "retrieval_degraded_count",
            "qa_degraded_count",
            "us_generation_degraded_count",
            "impact_analysis_degraded_count",
        ]
    )
    if degraded_count:
        return "TUNE_GRAPH_AWARE_EVAL"
    if issue_summary["unsupported_claim_count"]:
        return "FIX_GROUNDING"
    if issue_summary["invalid_citation_count"]:
        return "FIX_EVIDENCE_CITATION"
    if issue_summary["version_review_required_count"] > 20:
        return "TUNE_VERSION_RELATION_POLICY"
    return "READY_FOR_USER_EFFECT_REVIEW"


def _write_issue_outputs(
    output_root: Path,
    final_summary: dict[str, Any],
    backlog: list[dict[str, Any]],
) -> list[str]:
    written: list[str] = []
    written.extend(_write_pair(output_root / "06_issue_summary", "final_e2e_summary", final_summary, title="Final E2E Summary"))
    written.extend(_write_pair(output_root / "06_issue_summary", "optimization_backlog", backlog, title="Optimization Backlog"))
    return written


def _result_from_outputs(
    output_root: Path,
    source_file: Path,
    namespace: str,
    workspace: Path,
    ingestion_data: dict[str, Any],
    retrieval_summary: dict[str, Any],
    business_summary: dict[str, Any],
    us_summary: dict[str, Any],
    impact_summary: dict[str, Any],
    final_summary: dict[str, Any],
    backlog: list[dict[str, Any]],
    readme_path: Path,
    report_files: list[str],
) -> Lc66UsEffectTestResult:
    return Lc66UsEffectTestResult(
        output_dir=str(output_root),
        input_file=str(source_file),
        namespace=namespace,
        working_dir=str(workspace),
        source_us_count=int(ingestion_data.get("source_us_count") or 0),
        source_text_unit_count=int(ingestion_data.get("source_text_unit_count") or 0),
        graph_write_succeeded=bool(ingestion_data.get("graph_write_succeeded")),
        custom_kg_chunk_count=int(ingestion_data.get("custom_kg_chunk_count") or 0),
        custom_kg_entity_count=int(ingestion_data.get("custom_kg_entity_count") or 0),
        custom_kg_relationship_count=int(ingestion_data.get("custom_kg_relationship_count") or 0),
        retrieval_improved_count=int((retrieval_summary or {}).get("improved_count") or 0),
        retrieval_degraded_count=int((retrieval_summary or {}).get("degraded_count") or 0),
        business_qa_improved_count=int((business_summary or {}).get("improved_count") or 0),
        business_qa_degraded_count=int((business_summary or {}).get("degraded_count") or 0),
        us_generation_improved_count=int((us_summary or {}).get("improved_count") or 0),
        us_generation_degraded_count=int((us_summary or {}).get("degraded_count") or 0),
        impact_analysis_improved_count=int((impact_summary or {}).get("improved_count") or 0),
        impact_analysis_degraded_count=int((impact_summary or {}).get("degraded_count") or 0),
        unsupported_claim_count=int(final_summary.get("unsupported_claim_count") or 0),
        invalid_citation_count=int(final_summary.get("invalid_citation_count") or 0),
        version_review_required_count=int(final_summary.get("version_review_required_count") or 0),
        optimization_backlog_count=len(backlog),
        readme_path=str(readme_path),
        neo4j_connected=bool(ingestion_data.get("neo4j_connected")),
        production_write=bool(ingestion_data.get("production_write")),
        real_llm_called=bool(
            (business_summary or {}).get("llm_called")
            or (us_summary or {}).get("llm_called")
            or (impact_summary or {}).get("llm_called")
        ),
        lightrag_core_modified=bool(_core_diff_names()),
        recommended_next_step=str(final_summary.get("recommended_next_step") or ""),
        report_files=report_files,
    )


def _ensure_output_dirs(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for item in REPORT_DIRS:
        (output_root / item).mkdir(parents=True, exist_ok=True)


def _clear_workspace_if_safe(workspace: Path, output_root: Path) -> None:
    workspace = workspace.resolve()
    output_root = output_root.resolve()
    if workspace == output_root or output_root not in workspace.parents:
        raise RuntimeError(f"Unsafe test graph workspace: {workspace}")
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)


def _write_pair(directory: Path, name: str, data: Any, *, title: str) -> list[str]:
    json_path = _write_json(directory / f"{name}.json", data)
    md_path = _write_text(directory / f"{name}.md", _markdown_kv(title, data))
    return [str(json_path), str(md_path)]


def _write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _markdown_kv(title: str, data: Any) -> str:
    return f"# {title}\n\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```\n"


def _generated_us_samples(data: dict[str, Any]) -> str:
    parts = ["# Generated US Samples\n"]
    for item in data.get("case_results", [])[:3]:
        case_id = (item.get("case") or {}).get("case_id")
        graph = item.get("graph_result") or {}
        parts.append(f"## {case_id}\n\n{graph.get('generated_us_markdown', '')}\n")
    return "\n".join(parts)


def _impact_samples(data: dict[str, Any]) -> str:
    parts = ["# Impact Analysis Samples\n"]
    for item in data.get("case_results", [])[:3]:
        case_id = (item.get("case") or {}).get("case_id")
        graph = item.get("graph_result") or {}
        parts.append(f"## {case_id}\n\n{graph.get('analysis_markdown', '')}\n")
    return "\n".join(parts)


def _write_readme(
    output_root: Path,
    source_file: Path,
    namespace: str,
    workspace: Path,
    ingestion: dict[str, Any],
    retrieval: dict[str, Any],
    business: dict[str, Any],
    us_generation: dict[str, Any],
    impact: dict[str, Any],
    issue_summary: dict[str, Any],
    backlog: list[dict[str, Any]],
) -> Path:
    text = "\n".join(
        [
            "# LC 66US Test Graph Effect Test",
            "",
            "## Target",
            "Offline deterministic effect test for LC acceptable bank 66 US using test namespace graph ingestion.",
            "",
            f"- Input US file: `{source_file}`",
            f"- Output directory: `{output_root}`",
            f"- Test graph working_dir: `{workspace}`",
            f"- Namespace: `{namespace}`",
            "",
            "## Output Structure",
            *[f"- `{item}/`" for item in REPORT_DIRS],
            "",
            "## Ingestion Summary",
            _compact_json(ingestion, ["graph_write_succeeded", "custom_kg_chunk_count", "custom_kg_entity_count", "custom_kg_relationship_count", "sidecar_alignment_passed", "endpoint_closure_passed", "neo4j_connected", "production_write"]),
            "",
            "## Retrieval Summary",
            _compact_json(retrieval, ["query_count", "improved_count", "degraded_count", "recommended_next_step"]),
            "",
            "## Business QA Summary",
            _compact_json(business, ["case_count", "improved_count", "degraded_count", "avg_score_delta", "recommended_next_step"]),
            "",
            "## US Generation Summary",
            _compact_json(us_generation, ["case_count", "improved_count", "degraded_count", "avg_score_delta", "recommended_next_step"]),
            "",
            "## Impact Analysis Summary",
            _compact_json(impact, ["case_count", "improved_count", "degraded_count", "avg_score_delta", "recommended_next_step"]),
            "",
            "## Issue Summary",
            _compact_json(issue_summary, list(issue_summary.keys())),
            "",
            "## Optimization Backlog",
            _compact_json({"items": backlog}, ["items"]),
            "",
            "## Safety Boundary",
            "- no production graph",
            "- no Neo4j",
            "- no real LLM",
            "- no LightRAG core modification",
            "- test namespace only",
            "",
            "## How To Review",
            "Open the JSON and Markdown files under each numbered directory. Use the retained test graph working_dir and namespace for later offline effect checks.",
            "",
        ]
    )
    return _write_text(output_root / "README.md", text)


def _write_run_manifest(
    output_root: Path,
    source_file: Path,
    workspace: Path,
    namespace: str,
    report_files: list[str],
    started: float,
) -> Path:
    artifacts = [
        str(path)
        for path in sorted((output_root / "test_graph_workspace").glob("**/*"))
        if path.is_file()
    ]
    manifest = {
        "run_id": f"lc-66us-effect-{int(started)}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_file": str(source_file),
        "output_dir": str(output_root),
        "working_dir": str(workspace),
        "namespace": namespace,
        "git_status_summary": _git_status_summary(),
        "command_results": {
            "mode": "offline",
            "graph_storage_type": SMOKE_GRAPH_STORAGE,
            "real_llm_called": False,
            "neo4j_connected": False,
            "production_write": False,
        },
        "report_files": report_files,
        "artifact_files": artifacts,
    }
    return _write_json(output_root / "run_manifest.json", manifest)


def _write_run_log(output_root: Path, log_lines: list[str], started: float) -> None:
    lines = [
        f"started={time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(started))}",
        *log_lines,
        f"elapsed_ms={int((time.time() - started) * 1000)}",
    ]
    _write_text(output_root / "07_logs" / "effect_test.log", "\n".join(lines) + "\n")


def _compact_json(data: dict[str, Any], keys: list[str]) -> str:
    return "```json\n" + json.dumps({key: data.get(key) for key in keys}, indent=2, ensure_ascii=False) + "\n```"


def _info_only_as_fact_count(data: dict[str, Any]) -> int:
    return sum(
        int(((item.get("graph_judgement") or {}).get("info_only_as_fact_count")) or 0)
        for item in data.get("case_results", [])
    )


def _unsupported_claims(data: dict[str, Any] | None) -> int:
    return sum(
        int(((item.get("graph_judgement") or {}).get("unsupported_claim_count")) or 0)
        for item in (data or {}).get("case_results", [])
    )


def _invalid_citations(data: dict[str, Any] | None) -> int:
    return sum(
        int(((item.get("graph_judgement") or {}).get("invalid_citation_count")) or 0)
        for item in (data or {}).get("case_results", [])
    )


def _candidate_as_confirmed(data: dict[str, Any] | None) -> int:
    return sum(
        int(((item.get("graph_judgement") or {}).get("candidate_as_confirmed_count")) or 0)
        for item in (data or {}).get("case_results", [])
    )


def _source_span_missing(data: dict[str, Any] | None) -> int:
    return sum(
        1
        for item in (data or {}).get("case_results", [])
        if int(((item.get("graph_judgement") or {}).get("source_span_score")) or 0) <= 0
    )


def _case_result_label(data: dict[str, Any], case_id: str) -> str:
    for item in data.get("case_results", []):
        case = item.get("case") or {}
        actual_case_id = str(case.get("case_id") or "")
        if actual_case_id == case_id or actual_case_id.startswith(f"{case_id}-"):
            comparison = item.get("comparison") or {}
            return str(comparison.get("improvement_label") or item.get("graph_coverage_status") or "")
    return "NOT_RUN"


def _judgement_count(data: dict[str, Any], result: str) -> int:
    return sum(
        1
        for item in data.get("case_results", [])
        if ((item.get("graph_judgement") or {}).get("result")) == result
    )


def _git_status_summary() -> dict[str, Any]:
    return {
        "status_short": _git_command(["git", "status", "--short"]),
        "core_diff_names": _core_diff_names(),
    }


def _core_diff_names() -> list[str]:
    text = _git_command(["git", "diff", "--name-only", "--", "lightrag"])
    return [line for line in text.splitlines() if line.strip()]


def _git_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


__all__ = [
    "DEFAULT_LC_US_FILE",
    "DEFAULT_OUTPUT_DIR",
    "FIXTURE_LC_US_FILE",
    "Lc66UsEffectTestResult",
    "run_lc_66us_e2e_effect_test",
    "serialize_lc_66us_effect_test_result",
]
