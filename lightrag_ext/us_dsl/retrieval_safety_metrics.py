from __future__ import annotations

from .multi_module_eval_types import CaseRetrievalResult, SafetyMetrics


def compute_retrieval_safety_metrics(results: list[CaseRetrievalResult]) -> SafetyMetrics:
    hits = [hit for result in results for hit in result.hits]
    return SafetyMetrics(
        invalid_citation_count=sum(1 for hit in hits if not hit.has_citation),
        unsupported_factual_path_count=sum(1 for hit in hits if hit.unsupported_factual_path),
        issue_as_fact_count=sum(1 for hit in hits if hit.issue_as_fact),
        candidate_as_confirmed_count=sum(1 for hit in hits if hit.candidate_as_confirmed),
        info_only_as_fact_count=sum(1 for hit in hits if hit.info_only_as_fact),
        generic_graph_override_count=sum(1 for hit in hits if hit.generic_graph_override),
        generic_ner_fact_hit_count=sum(1 for hit in hits if hit.generic_ner_fact_hit),
        version_hard_judgment_error_count=sum(1 for hit in hits if hit.version_hard_judgment_error),
        missing_version_warning_count=sum(1 for hit in hits if hit.missing_version_warning),
    )


def safety_passes_primary_gate(metrics: SafetyMetrics) -> bool:
    return all(
        value == 0
        for value in [
            metrics.invalid_citation_count,
            metrics.unsupported_factual_path_count,
            metrics.issue_as_fact_count,
            metrics.candidate_as_confirmed_count,
            metrics.info_only_as_fact_count,
            metrics.generic_graph_override_count,
            metrics.generic_ner_fact_hit_count,
            metrics.version_hard_judgment_error_count,
        ]
    )
