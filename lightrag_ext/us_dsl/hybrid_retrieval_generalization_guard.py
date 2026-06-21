from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

FORBIDDEN_RUNTIME_TERMS = (
    "Bank Status",
    "查询条件",
    "银行状态",
    "设计文档",
    "LC",
)


@dataclass(frozen=True)
class HybridRetrievalGeneralizationReport:
    scanned_files: list[str] = field(default_factory=list)
    runtime_business_hardcode_count: int = 0
    entity_name_specific_weight_rule_count: int = 0
    module_specific_channel_weight_count: int = 0
    fixture_name_runtime_coupling_count: int = 0
    findings: list[dict[str, object]] = field(default_factory=list)


def inspect_hybrid_retrieval_generalization(module_dir: str | Path) -> HybridRetrievalGeneralizationReport:
    base = Path(module_dir)
    runtime_file_names = {
        "evidence_path_validator.py",
        "generic_graph_retrieval_adapter.py",
        "hybrid_retrieval_fallback.py",
        "hybrid_retrieval_service.py",
        "hybrid_retrieval_types.py",
        "issue_sidecar_retrieval_adapter.py",
        "pfss_retrieval_adapter.py",
        "query_semantic_profile.py",
        "raw_text_retrieval_adapter.py",
        "retrieval_candidate_deduplicator.py",
        "retrieval_candidate_normalizer.py",
        "trusted_context_builder.py",
        "trust_aware_rank_fusion.py",
    }
    runtime_files = sorted(base / name for name in runtime_file_names if (base / name).exists())
    findings: list[dict[str, object]] = []
    hardcode_count = 0
    weight_rule_count = 0
    module_weight_count = 0
    fixture_coupling_count = 0
    for path in runtime_files:
        text = path.read_text(encoding="utf-8")
        for term in FORBIDDEN_RUNTIME_TERMS:
            if term and term in text:
                hardcode_count += text.count(term)
                findings.append({"file": str(path), "term": term, "type": "business_hardcode"})
        lowered = text.casefold()
        if "semantic_object_id" in lowered and "weight" in lowered and "==" in lowered:
            weight_rule_count += 1
            findings.append({"file": str(path), "type": "entity_specific_weight_rule"})
        if "module_code" in lowered and "channel_weight" in lowered:
            module_weight_count += 1
            findings.append({"file": str(path), "type": "module_specific_channel_weight"})
        if "fixture" in lowered and "candidate" in lowered:
            fixture_coupling_count += 1
            findings.append({"file": str(path), "type": "fixture_runtime_coupling"})
    return HybridRetrievalGeneralizationReport(
        scanned_files=[str(path) for path in runtime_files],
        runtime_business_hardcode_count=hardcode_count,
        entity_name_specific_weight_rule_count=weight_rule_count,
        module_specific_channel_weight_count=module_weight_count,
        fixture_name_runtime_coupling_count=fixture_coupling_count,
        findings=findings,
    )
