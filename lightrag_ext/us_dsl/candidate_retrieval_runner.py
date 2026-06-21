from __future__ import annotations

from .multi_module_eval_types import CaseRetrievalResult, EvaluationCase, RetrievalHit


class CandidateRetrievalRunner:
    """Deterministic 26A context-pack adapter used by offline tests only."""

    def run_cases(self, cases: list[EvaluationCase]) -> list[CaseRetrievalResult]:
        results: list[CaseRetrievalResult] = []
        for case in cases:
            hits = [
                RetrievalHit(
                    hit_id=f"candidate-{case.case_id}-{index}",
                    module_code=case.module_code,
                    source_ref=source_ref,
                    source_us_id=case.gold_source_us_ids[min(index, len(case.gold_source_us_ids) - 1)] if case.gold_source_us_ids else None,
                    text_unit_id=case.gold_text_unit_ids[min(index, len(case.gold_text_unit_ids) - 1)] if case.gold_text_unit_ids else None,
                    source_span={"start": index * 10, "end": index * 10 + 20},
                    evidence_keywords=case.gold_evidence_keywords,
                    semantic_object_id=case.gold_semantic_object_ids[min(index, len(case.gold_semantic_object_ids) - 1)] if case.gold_semantic_object_ids else None,
                    relation_type=case.gold_relation_types[min(index, len(case.gold_relation_types) - 1)] if case.gold_relation_types else None,
                    required_dimensions=case.gold_required_dimensions,
                    graph_path_id="candidate-path" if case.gold_relation_types or case.gold_required_dimensions else None,
                )
                for index, source_ref in enumerate(case.gold_source_refs[:2] or [None])
            ]
            results.append(
                CaseRetrievalResult(
                    case_id=case.case_id,
                    module_code=case.module_code,
                    group="candidate",
                    hits=hits,
                    warmup_latency_ms=16.0,
                    latency_ms_runs=[15.0, 16.0, 17.0, 18.0, 19.0],
                )
            )
        return results
