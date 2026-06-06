from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Any, ClassVar

from .confirmed_graph_write_dry_run import (
    ConfirmedGraphWriteDryRunConfig,
    run_confirmed_graph_write_dry_run,
)
from .e2e_graph_pipeline_report import (
    E2EGraphPipelineReport,
    IssueSummary,
    OptimizationBacklogItem,
    serialize_e2e_graph_pipeline_report,
)
from .graph_retrieval_eval import build_graph_retrieval_evaluation_report
from .kg_metadata_sidecar import build_graph_insert_sidecar_records
from .kg_real_graph_smoke import SMOKE_GRAPH_STORAGE
from .kg_test_graph_write import to_lightrag_custom_kg_input
from .lc_business_qa_cases import default_lc_business_qa_cases
from .lc_business_qa_eval import (
    run_lc_business_qa_ab_eval,
)
from .lc_graph_subset_builder import (
    ExpandedGraphSubsetResult,
    build_lc_expanded_graph_subset_from_case_pack,
)
from .lc_impact_analysis_eval import run_lc_impact_analysis_ab_eval
from .lc_mini_graph_smoke import (
    LC_SOURCE_NAME,
    LcMiniGraphSmokeConfig,
    build_lc_mini_build_result,
)
from .lc_us_generation_eval import run_lc_us_generation_ab_eval
from .policy_auto_approval import (
    PolicyAutoApprovalConfig,
    PolicyAutoApprovalResult,
    run_policy_auto_approval,
)
from .promotion_gate import build_confirmed_graph_write_plan, build_promotion_candidates
from .promotion_types import TARGET_TEST_GRAPH
from .version_issue_triage import build_version_issue_triage_report
from .version_relation_builder import extract_versioned_semantic_objects


ENABLE_E2E_GRAPH_PIPELINE_ENV = "LIGHTRAG_ENABLE_DSL_AWARE_E2E_GRAPH_PIPELINE"


@dataclass
class E2EGraphPipelineConfig:
    __test__: ClassVar[bool] = False

    enabled: bool = False
    source: str = "lc"
    namespace: str = "dsl_test_e2e_graph"
    test_namespace_only: bool = True
    use_temp_working_dir: bool = True
    force_local_graph_storage: bool = True
    isolate_remote_graph_env: bool = True
    allow_neo4j: bool = False
    use_fake_embedding: bool = True
    use_fake_llm: bool = True
    cleanup_after_run: bool = True
    rollback_after_run: bool = True
    max_chunks: int = 15
    max_entities: int = 30
    max_relationships: int = 20
    run_retrieval_eval: bool = True
    run_business_qa_eval: bool = True
    run_us_generation_eval: bool = True
    run_impact_analysis_eval: bool = True
    timeout_seconds: int = 180
    feature_flag_name: str = "enable_dsl_aware_e2e_graph_pipeline"

    @classmethod
    def from_env(cls) -> "E2EGraphPipelineConfig":
        return cls(enabled=os.getenv(ENABLE_E2E_GRAPH_PIPELINE_ENV) == "1")


def run_e2e_graph_pipeline(
    *,
    source: str = "LC_Acceptable_Bank_US_v1",
    mode: str = "offline",
    graph_scope: str = "expanded_lc_subset",
    config: E2EGraphPipelineConfig | None = None,
) -> E2EGraphPipelineReport:
    config = config or E2EGraphPipelineConfig.from_env()
    if not config.enabled:
        return E2EGraphPipelineReport(
            source=source,
            namespace=config.namespace,
            enabled=False,
            skipped=True,
            skip_reason="Feature flag enable_dsl_aware_e2e_graph_pipeline is disabled.",
            source_us_count=0,
            source_text_unit_count=0,
            kg_payload_chunk_count=0,
            kg_payload_entity_count=0,
            kg_payload_relationship_count=0,
            approved_for_test_graph_count=0,
            blocked_from_graph_count=0,
            block_reason_distribution={},
            custom_kg_chunk_count=0,
            custom_kg_entity_count=0,
            custom_kg_relationship_count=0,
            sidecar_record_count=0,
            sidecar_alignment_passed=False,
            governance_passed=False,
            graph_write_attempted=False,
            graph_write_succeeded=False,
            neo4j_connected=False,
            production_write=False,
            formal_graph_written=False,
            rollback_passed=False,
            cleanup_passed=True,
            recommended_next_step="ENABLE_E2E_GRAPH_PIPELINE",
        )

    build_result = build_lc_mini_build_result(
        LcMiniGraphSmokeConfig(
            max_chunks=100,
            max_entities=100,
            max_relationships=100,
        )
    )
    cases = default_lc_business_qa_cases()
    subset = build_lc_expanded_graph_subset_from_case_pack(
        kg_payload=build_result.payload,
        cases=cases,
        max_chunks=config.max_chunks,
        max_entities=config.max_entities,
        max_relationships=config.max_relationships,
        namespace=config.namespace,
    )
    version_triage_report = build_version_issue_triage_report(
        extract_versioned_semantic_objects(kg_payload=subset.subset_payload)
    )
    policy_result = _run_policy_gate(subset, config=config, source=source)
    plan = build_confirmed_graph_write_plan(
        build_promotion_candidates(
            kg_payload=subset.subset_payload,
            sidecar_records=subset.graph_insert_sidecar_records,
        ),
        manifest=policy_result.manifest,
        target_namespace=config.namespace,
        dry_run=True,
        target_graph_type=TARGET_TEST_GRAPH,
    )
    write_report = run_confirmed_graph_write_dry_run(
        plan=plan,
        config=ConfirmedGraphWriteDryRunConfig(
            enabled=True,
            dry_run=True,
            test_namespace_only=config.test_namespace_only,
            target_graph_type=TARGET_TEST_GRAPH,
            namespace=config.namespace,
            workspace=config.namespace,
            use_temp_working_dir=config.use_temp_working_dir,
            force_local_graph_storage=config.force_local_graph_storage,
            local_graph_storage=SMOKE_GRAPH_STORAGE,
            graph_storage_type=SMOKE_GRAPH_STORAGE,
            isolate_remote_graph_env=config.isolate_remote_graph_env,
            allow_neo4j=config.allow_neo4j,
            use_fake_embedding=config.use_fake_embedding,
            use_fake_llm=config.use_fake_llm,
            cleanup_after_run=config.cleanup_after_run,
            rollback_after_run=config.rollback_after_run,
            max_entities=config.max_entities,
            max_relationships=config.max_relationships,
            timeout_seconds=config.timeout_seconds,
            manifest_type="TEST_MANIFEST",
        ),
    )

    retrieval_report = (
        build_graph_retrieval_evaluation_report(
            source=source,
            payload=subset.subset_payload,
            sidecar_records=subset.graph_insert_sidecar_records,
            max_queries=8,
        )
        if config.run_retrieval_eval
        else None
    )
    business_report = (
        run_lc_business_qa_ab_eval(
            mode=mode,
            max_cases=10,
            use_expanded_subset=graph_scope == "expanded_lc_subset",
        )
        if config.run_business_qa_eval
        else None
    )
    us_report = (
        run_lc_us_generation_ab_eval(
            mode=mode,
            max_cases=8,
            use_expanded_subset=graph_scope == "expanded_lc_subset",
        )
        if config.run_us_generation_eval
        else None
    )
    impact_report = (
        run_lc_impact_analysis_ab_eval(
            mode=mode,
            max_cases=6,
            use_expanded_subset=graph_scope == "expanded_lc_subset",
        )
        if config.run_impact_analysis_eval
        else None
    )

    issue_summary = _issue_summary(
        subset=subset,
        policy_result=policy_result,
        graph_write_succeeded=write_report.graph_write_succeeded,
        retrieval_summary=_retrieval_summary(retrieval_report),
        business_report=business_report,
        us_report=us_report,
        impact_report=impact_report,
    )
    backlog = _optimization_backlog(
        issue_summary=issue_summary,
        policy_result=policy_result,
        write_succeeded=write_report.graph_write_succeeded,
        sidecar_alignment_passed=write_report.sidecar_alignment_passed,
    )
    risks = _dedupe(
        [
            *subset.risks,
            *write_report.risks,
            *(business_report.risks if business_report is not None else []),
            *(us_report.risks if us_report is not None else []),
            *(impact_report.risks if impact_report is not None else []),
        ]
    )

    return E2EGraphPipelineReport(
        source=source or LC_SOURCE_NAME,
        namespace=config.namespace,
        enabled=True,
        skipped=False,
        skip_reason=None,
        source_us_count=build_result.source_us_count,
        source_text_unit_count=build_result.source_text_unit_count,
        kg_payload_chunk_count=len(build_result.payload.chunks),
        kg_payload_entity_count=len(build_result.payload.entities),
        kg_payload_relationship_count=len(build_result.payload.relationships),
        approved_for_test_graph_count=policy_result.approved_for_test_graph_count,
        blocked_from_graph_count=policy_result.blocked_from_graph_count,
        block_reason_distribution=policy_result.block_reason_distribution,
        custom_kg_chunk_count=write_report.custom_kg_chunk_count,
        custom_kg_entity_count=write_report.custom_kg_entity_count,
        custom_kg_relationship_count=write_report.custom_kg_relationship_count,
        sidecar_record_count=write_report.sidecar_record_count,
        sidecar_alignment_passed=write_report.sidecar_alignment_passed,
        governance_passed=write_report.governance_passed,
        graph_write_attempted=write_report.graph_write_attempted,
        graph_write_succeeded=write_report.graph_write_succeeded,
        neo4j_connected=write_report.neo4j_connected,
        production_write=write_report.production_write,
        formal_graph_written=write_report.formal_graph_written,
        rollback_passed=write_report.rollback_passed,
        cleanup_passed=write_report.cleanup_passed,
        retrieval_eval_summary=_retrieval_summary(retrieval_report),
        business_qa_eval_summary=_business_qa_summary(business_report),
        us_generation_eval_summary=_us_generation_summary(us_report),
        impact_analysis_eval_summary=_impact_analysis_summary(impact_report),
        version_issue_triage_summary=_version_triage_summary(version_triage_report),
        version_review_required_before=version_triage_report.review_required_before_count,
        version_review_required_after=version_triage_report.review_required_after_count,
        version_review_required_reduction=version_triage_report.review_required_reduction_count,
        version_safe_for_test_count=policy_result.version_safe_for_test_count,
        version_formal_blocked_count=policy_result.version_formal_blocked_count,
        true_version_review_required_count=version_triage_report.true_review_required_count,
        unsafe_supersedes_blocked_count=version_triage_report.unsafe_supersedes_blocked_count,
        issue_summary=issue_summary,
        optimization_backlog=backlog,
        recommended_next_step=_recommended_next_step(issue_summary, write_report.graph_write_succeeded),
        risks=risks,
        llm_called=any(
            [
                bool(getattr(business_report, "llm_called", False)),
                bool(getattr(us_report, "llm_called", False)),
                bool(getattr(impact_report, "llm_called", False)),
            ]
        ),
        test_only=True,
    )


def _run_policy_gate(
    subset: ExpandedGraphSubsetResult,
    *,
    config: E2EGraphPipelineConfig,
    source: str,
) -> PolicyAutoApprovalResult:
    custom_kg = to_lightrag_custom_kg_input(subset.subset_payload)
    sidecar_records = build_graph_insert_sidecar_records(
        subset.subset_payload,
        custom_kg,
        namespace=config.namespace,
    )
    candidates = build_promotion_candidates(
        kg_payload=subset.subset_payload,
        sidecar_records=sidecar_records,
    )
    return run_policy_auto_approval(
        candidates,
        config=PolicyAutoApprovalConfig(namespace=config.namespace),
        module_name="LC",
        source_document=source,
    )


def _retrieval_summary(report: Any | None) -> dict[str, Any]:
    if report is None:
        return {}
    return {
        "query_count": report.query_count,
        "improved_count": report.improved_count,
        "same_count": report.same_count,
        "degraded_count": report.degraded_count,
        "inconclusive_count": report.inconclusive_count,
        "avg_entity_recall_delta": report.avg_entity_recall_delta,
        "avg_relation_recall_delta": report.avg_relation_recall_delta,
        "avg_evidence_coverage_delta": report.avg_evidence_coverage_delta,
        "avg_source_span_coverage_delta": report.avg_source_span_coverage_delta,
        "avg_graph_path_delta": report.avg_graph_path_delta,
        "recommended_next_step": report.recommended_next_step,
    }


def _business_qa_summary(report: Any | None) -> dict[str, Any]:
    if report is None:
        return {}
    return {
        "case_count": report.case_count,
        "text_only_pass_count": report.text_only_pass_count,
        "graph_aware_pass_count": report.graph_aware_pass_count,
        "improved_count": report.improved_count,
        "same_count": report.same_count,
        "degraded_count": report.degraded_count,
        "inconclusive_count": report.inconclusive_count,
        "avg_text_score": report.avg_text_score,
        "avg_graph_score": report.avg_graph_score,
        "avg_score_delta": report.avg_score_delta,
        "avg_unsupported_claim_delta": report.avg_unsupported_claim_delta,
        "graph_path_used_count": report.graph_path_used_count,
        "recommended_next_step": report.recommended_next_step,
    }


def _us_generation_summary(report: Any | None) -> dict[str, Any]:
    if report is None:
        return {}
    return {
        "case_count": report.case_count,
        "text_only_pass_count": report.text_only_pass_count,
        "graph_aware_pass_count": report.graph_aware_pass_count,
        "improved_count": report.improved_count,
        "same_count": report.same_count,
        "degraded_count": report.degraded_count,
        "inconclusive_count": report.inconclusive_count,
        "avg_text_score": report.avg_text_score,
        "avg_graph_score": report.avg_graph_score,
        "avg_score_delta": report.avg_score_delta,
        "avg_unsupported_claim_delta": report.avg_unsupported_claim_delta,
        "avg_structure_completeness_delta": report.avg_structure_completeness_delta,
        "avg_business_rule_coverage_delta": report.avg_business_rule_coverage_delta,
        "avg_review_readiness_delta": report.avg_review_readiness_delta,
        "graph_path_used_count": report.graph_path_used_count,
        "accept_as_is_count": report.accept_as_is_count,
        "accept_with_minor_edits_count": report.accept_with_minor_edits_count,
        "need_major_revision_count": report.need_major_revision_count,
        "reject_count": report.reject_count,
        "recommended_next_step": report.recommended_next_step,
    }


def _impact_analysis_summary(report: Any | None) -> dict[str, Any]:
    if report is None:
        return {}
    return {
        "case_count": report.case_count,
        "text_only_pass_count": report.text_only_pass_count,
        "graph_aware_pass_count": report.graph_aware_pass_count,
        "improved_count": report.improved_count,
        "same_count": report.same_count,
        "degraded_count": report.degraded_count,
        "inconclusive_count": report.inconclusive_count,
        "avg_text_score": report.avg_text_score,
        "avg_graph_score": report.avg_graph_score,
        "avg_score_delta": report.avg_score_delta,
        "avg_unsupported_claim_delta": report.avg_unsupported_claim_delta,
        "avg_relation_path_delta": report.avg_relation_path_delta,
        "graph_path_used_count": report.graph_path_used_count,
        "recommended_next_step": report.recommended_next_step,
    }


def _version_triage_summary(report: Any) -> dict[str, Any]:
    return {
        "total_version_groups": report.total_version_groups,
        "singleton_no_conflict_count": report.singleton_no_conflict_count,
        "explicit_current_count": report.explicit_current_count,
        "explicit_supersedes_count": report.explicit_supersedes_count,
        "weak_version_keyword_only_count": report.weak_version_keyword_only_count,
        "multi_version_unknown_count": report.multi_version_unknown_count,
        "conflict_without_supersedes_count": report.conflict_without_supersedes_count,
        "true_review_required_count": report.true_review_required_count,
        "review_required_before_count": report.review_required_before_count,
        "review_required_after_count": report.review_required_after_count,
        "review_required_reduction_count": report.review_required_reduction_count,
        "unsafe_supersedes_blocked_count": report.unsafe_supersedes_blocked_count,
        "recommended_next_step": report.recommended_next_step,
    }


def _issue_summary(
    *,
    subset: ExpandedGraphSubsetResult,
    policy_result: PolicyAutoApprovalResult,
    graph_write_succeeded: bool,
    retrieval_summary: dict[str, Any],
    business_report: Any | None,
    us_report: Any | None,
    impact_report: Any | None,
) -> IssueSummary:
    reason_counts = Counter(policy_result.block_reason_distribution)
    return IssueSummary(
        unsupported_claim_count=(
            _unsupported_claims_from_case_results(getattr(business_report, "case_results", []))
            + _unsupported_claims_from_case_results(getattr(us_report, "case_results", []))
            + _unsupported_claims_from_case_results(getattr(impact_report, "case_results", []))
        ),
        invalid_citation_count=(
            int(getattr(business_report, "cases_with_invalid_citation", 0))
            + _invalid_citations_from_case_results(getattr(us_report, "case_results", []))
            + int(getattr(impact_report, "cases_with_invalid_citation", 0))
        ),
        candidate_as_confirmed_count=(
            int(getattr(business_report, "cases_with_candidate_as_confirmed", 0))
            + _candidate_as_confirmed_from_case_results(getattr(us_report, "case_results", []))
            + int(getattr(impact_report, "cases_with_candidate_as_confirmed", 0))
        ),
        info_only_as_fact_count=(
            _info_only_from_case_results(getattr(business_report, "case_results", []))
            + _info_only_from_case_results(getattr(us_report, "case_results", []))
            + _info_only_from_case_results(getattr(impact_report, "case_results", []))
        ),
        missing_evidence_count=reason_counts.get("MISSING_EVIDENCE", 0),
        version_review_required_count=sum(
            count for reason, count in reason_counts.items() if "VERSION" in reason
        ),
        forbidden_relation_count=subset.forbidden_relation_count,
        dangling_relationship_count=subset.dangling_relationship_count,
        sidecar_mismatch_count=0 if subset.sidecar_alignment_passed else 1,
        graph_write_failure_count=0 if graph_write_succeeded else 1,
        retrieval_degraded_count=int(retrieval_summary.get("degraded_count", 0)),
        qa_degraded_count=int(getattr(business_report, "degraded_count", 0)),
        us_generation_degraded_count=int(getattr(us_report, "degraded_count", 0)),
        impact_analysis_degraded_count=int(getattr(impact_report, "degraded_count", 0)),
    )


def _optimization_backlog(
    *,
    issue_summary: IssueSummary,
    policy_result: PolicyAutoApprovalResult,
    write_succeeded: bool,
    sidecar_alignment_passed: bool,
) -> list[OptimizationBacklogItem]:
    backlog: list[OptimizationBacklogItem] = []
    if not write_succeeded:
        backlog.append(
            OptimizationBacklogItem(
                issue_type="GRAPH_WRITE_FAILURE",
                severity="HIGH",
                description="Test graph write did not complete successfully.",
                recommended_fix="Inspect governance, custom_kg schema, and local graph storage isolation.",
                owner_hint="platform",
                next_block_hint="FIX_GRAPH_WRITE_GOVERNANCE",
            )
        )
    if not sidecar_alignment_passed or issue_summary.sidecar_mismatch_count:
        backlog.append(
            OptimizationBacklogItem(
                issue_type="SIDECAR_ALIGNMENT",
                severity="HIGH",
                description="Graph insert sidecar did not align with custom_kg input.",
                recommended_fix="Fix sidecar external-key generation before additional graph runs.",
                owner_hint="knowledge-pipeline",
                next_block_hint="FIX_SIDECAR_ALIGNMENT",
            )
        )
    degraded_count = (
        issue_summary.retrieval_degraded_count
        + issue_summary.qa_degraded_count
        + issue_summary.us_generation_degraded_count
        + issue_summary.impact_analysis_degraded_count
    )
    if degraded_count:
        backlog.append(
            OptimizationBacklogItem(
                issue_type="GRAPH_AWARE_EVAL_DEGRADED",
                severity="MEDIUM",
                description=f"Graph-aware eval degraded in {degraded_count} comparison groups.",
                recommended_fix="Tune graph retrieval seeds, path filtering, and grounding rules.",
                owner_hint="eval",
                next_block_hint="TUNE_GRAPH_AWARE_EVAL",
            )
        )
    if issue_summary.version_review_required_count:
        backlog.append(
            OptimizationBacklogItem(
                issue_type="VERSION_REVIEW_REQUIRED",
                severity="MEDIUM",
                description="Some version-related graph objects remain blocked from test graph policy approval.",
                recommended_fix="Improve explicit version evidence and reviewer workflow before formal promotion.",
                owner_hint="BA/SE + knowledge-pipeline",
                next_block_hint="TUNE_VERSION_RELATION_POLICY",
            )
        )
    if policy_result.blocked_from_graph_count:
        backlog.append(
            OptimizationBacklogItem(
                issue_type="POLICY_BLOCKED_OBJECTS",
                severity="LOW",
                description=(
                    f"{policy_result.blocked_from_graph_count} candidate objects were held out "
                    "by the test graph policy gate."
                ),
                recommended_fix="Review block reason distribution and decide whether evidence or schema fixes are needed.",
                owner_hint="knowledge-pipeline",
                next_block_hint="ISSUE_SUMMARY_REVIEW",
            )
        )
    if not backlog:
        backlog.append(
            OptimizationBacklogItem(
                issue_type="NEXT_OPTIMIZATION_ROUND",
                severity="LOW",
                description="E2E test graph pipeline completed without blocking issues.",
                recommended_fix="Review small-sample eval details before expanding scope.",
                owner_hint="team",
                next_block_hint="PREPARE_ISSUE_SUMMARY_AND_OPTIMIZATION_ROUND",
            )
        )
    return backlog


def _recommended_next_step(issue_summary: IssueSummary, graph_write_succeeded: bool) -> str:
    if not graph_write_succeeded:
        return "FIX_GRAPH_WRITE_GOVERNANCE"
    if issue_summary.sidecar_mismatch_count:
        return "FIX_SIDECAR_ALIGNMENT"
    degraded_count = (
        issue_summary.retrieval_degraded_count
        + issue_summary.qa_degraded_count
        + issue_summary.us_generation_degraded_count
        + issue_summary.impact_analysis_degraded_count
    )
    if degraded_count:
        return "TUNE_GRAPH_AWARE_EVAL"
    if issue_summary.version_review_required_count:
        return "TUNE_VERSION_RELATION_POLICY"
    return "PREPARE_ISSUE_SUMMARY_AND_OPTIMIZATION_ROUND"


def _unsupported_claims_from_case_results(case_results: list[Any]) -> int:
    return sum(
        int(getattr(item.graph_judgement, "unsupported_claim_count", 0))
        for item in case_results
        if hasattr(item, "graph_judgement")
    )


def _invalid_citations_from_case_results(case_results: list[Any]) -> int:
    return sum(
        int(getattr(item.graph_judgement, "invalid_citation_count", 0))
        for item in case_results
        if hasattr(item, "graph_judgement")
    )


def _candidate_as_confirmed_from_case_results(case_results: list[Any]) -> int:
    return sum(
        int(getattr(item.graph_judgement, "candidate_as_confirmed_count", 0))
        for item in case_results
        if hasattr(item, "graph_judgement")
    )


def _info_only_from_case_results(case_results: list[Any]) -> int:
    return sum(
        int(getattr(item.graph_judgement, "info_only_as_fact_count", 0))
        for item in case_results
        if hasattr(item, "graph_judgement")
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


__all__ = [
    "ENABLE_E2E_GRAPH_PIPELINE_ENV",
    "E2EGraphPipelineConfig",
    "run_e2e_graph_pipeline",
    "serialize_e2e_graph_pipeline_report",
]
