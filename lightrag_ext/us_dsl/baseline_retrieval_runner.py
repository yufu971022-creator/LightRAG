from __future__ import annotations

from .multi_module_eval_types import CaseRetrievalResult, EvaluationCase, RetrievalHit


class BaselineRetrievalRunner:
    """Deterministic evaluation adapter; real LightRAG execution is wired only by the CLI gate."""

    def run_cases(self, cases: list[EvaluationCase]) -> list[CaseRetrievalResult]:
        results: list[CaseRetrievalResult] = []
        for case in cases:
            hits = [
                RetrievalHit(
                    hit_id=f"baseline-{case.case_id}-0",
                    module_code=case.module_code,
                    source_ref=case.gold_source_refs[0] if case.gold_source_refs else None,
                    source_us_id=case.gold_source_us_ids[0] if case.gold_source_us_ids else None,
                    text_unit_id=case.gold_text_unit_ids[0] if case.gold_text_unit_ids else None,
                    source_span={"start": 0, "end": 20},
                    evidence_keywords=case.gold_evidence_keywords[:1],
                    semantic_object_id=case.gold_semantic_object_ids[0] if case.gold_semantic_object_ids else None,
                    relation_type=case.gold_relation_types[0] if case.gold_relation_types else None,
                    required_dimensions=case.gold_required_dimensions[:1],
                    graph_path_id="baseline-path" if case.gold_relation_types else None,
                )
            ]
            results.append(
                CaseRetrievalResult(
                    case_id=case.case_id,
                    module_code=case.module_code,
                    group="baseline",
                    hits=hits,
                    warmup_latency_ms=12.0,
                    latency_ms_runs=[10.0, 11.0, 12.0, 13.0, 14.0],
                )
            )
        return results
