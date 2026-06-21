from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.multi_module_eval_manifest import parse_multi_module_manifest
from lightrag_ext.us_dsl.multi_module_eval_types import (
    CaseRetrievalResult,
    EvaluationCase,
    MultiModuleManifest,
    RetrievalHit,
)


def write_manifest_tree(tmp_path: Path, *, module_count: int = 4, include_holdout: bool = True, domains: int = 5) -> MultiModuleManifest:
    module_codes = [f"MOD{index}" for index in range(module_count)]
    docs: list[Path] = []
    modules = []
    for index, code in enumerate(module_codes):
        doc = tmp_path / f"{code}.md"
        doc.write_text(f"document for {code}\n", encoding="utf-8")
        docs.append(doc)
        cases = [case_payload(f"{code}-case-{case_index}", code, str(doc)) for case_index in range(8)]
        cases_path = tmp_path / f"{code}_cases.json"
        cases_path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
        split = "HOLDOUT" if include_holdout and index == module_count - 1 else "CALIBRATION"
        modules.append(
            {
                "module_code": code,
                "module_name": f"Module {index}",
                "split": split,
                "source_files": [str(doc)],
                "cases_file": str(cases_path),
                "domains": [f"domain-{(index + offset) % max(domains, 1)}" for offset in range(2)],
            }
        )
    raw = {
        "suite_id": "fixture-suite",
        "output_dir": str(tmp_path / "out"),
        "policy": {
            "minimum_real_module_count": 3,
            "minimum_holdout_module_count": 1,
            "minimum_domain_coverage": 5,
            "minimum_case_count_per_module": 8,
            "max_raw_recall_regression": 0.02,
            "max_per_module_recall_regression": 0.05,
            "max_query_p95_latency_ratio": 2.5,
            "max_ingestion_time_ratio": 4.0,
        },
        "modules": modules,
    }
    return parse_multi_module_manifest(raw)


def case_payload(case_id: str, module_code: str, doc_path: str, *, one_to_n: bool = False) -> dict[str, object]:
    return {
        "case_id": case_id,
        "module_code": module_code,
        "task_type": "IMPACT_ANALYSIS" if one_to_n else "FACT_QA",
        "query": "fixture query",
        "strict_scope": False,
        "version_intent": "CURRENT",
        "as_of_time": None,
        "gold_source_refs": [doc_path],
        "gold_source_us_ids": [f"us-{case_id}"],
        "gold_text_unit_ids": [f"tu-{case_id}"],
        "gold_evidence_keywords": [f"kw-{case_id}"],
        "gold_semantic_object_ids": [f"obj-{case_id}"],
        "gold_relation_types": [f"rel-{case_id}"],
        "gold_required_dimensions": ["dimension-a", "dimension-b"] if one_to_n else ["dimension-a"],
        "gold_forbidden_claims": [],
        "gold_forbidden_claims_declared_none": True,
        "gold_version_behavior": "warn_on_conflict",
        "risk_level": "HIGH",
        "review_status": "REVIEWED",
        "one_to_n": one_to_n,
    }


def case_obj(case_id: str = "c1", module_code: str = "MOD0", doc_path: str = "/tmp/doc.md", *, one_to_n: bool = False) -> EvaluationCase:
    return EvaluationCase(**case_payload(case_id, module_code, doc_path, one_to_n=one_to_n))  # type: ignore[arg-type]


def hit_for(case: EvaluationCase, *, group: str = "candidate", missing: bool = False, flag: str | None = None) -> CaseRetrievalResult:
    hit = RetrievalHit(
        hit_id=f"{group}-{case.case_id}",
        module_code=case.module_code,
        source_ref=None if missing else case.gold_source_refs[0],
        source_us_id=None if missing else case.gold_source_us_ids[0],
        text_unit_id=None if missing else case.gold_text_unit_ids[0],
        source_span={} if missing else {"start": 0, "end": 10},
        evidence_keywords=[] if missing else list(case.gold_evidence_keywords),
        semantic_object_id=None if missing else case.gold_semantic_object_ids[0],
        relation_type=None if missing else case.gold_relation_types[0],
        required_dimensions=[] if missing else list(case.gold_required_dimensions),
        graph_path_id=None if missing else "path-1",
    )
    if flag:
        object.__setattr__(hit, flag, True)
    return CaseRetrievalResult(case.case_id, case.module_code, group, [hit], warmup_latency_ms=1.0, latency_ms_runs=[1, 2, 3, 4, 5])


def results_for(cases: list[EvaluationCase], *, group: str = "candidate", missing_module: str | None = None) -> list[CaseRetrievalResult]:
    return [hit_for(case, group=group, missing=case.module_code == missing_module) for case in cases]
