from __future__ import annotations

from .design_quality_types import FunctionalQAResult, ImpactAnalysisResult, QualityGateResult


def evaluate_evidence_citation(output: FunctionalQAResult | ImpactAnalysisResult) -> QualityGateResult:
    citations = {item.text_unit_id: item for item in output.source_citations}
    invalid = sum(1 for item in output.source_citations if not _valid_citation(item))
    missing = 0
    unsupported_fact = 0
    unsupported_path = 0
    for fact in getattr(output, "supporting_facts", []):
        if not fact.evidence_refs:
            unsupported_fact += 1
        missing += sum(1 for ref in fact.evidence_refs if ref not in citations)
    for path in getattr(output, "supporting_paths", []):
        refs = path.get("evidence_refs", [])
        if path.get("validation_status") == "FACTUAL" and not refs:
            unsupported_path += 1
        missing += sum(1 for ref in refs if ref not in citations)
    for item in _impact_items(output):
        if item.certainty in {"CONFIRMED", "SUPPORTED"} and not item.evidence_refs:
            unsupported_path += 1
        missing += sum(1 for ref in item.evidence_refs if ref not in citations)
    errors = []
    if invalid:
        errors.append("INVALID_CITATION")
    if missing:
        errors.append("MISSING_CITATION")
    if unsupported_fact:
        errors.append("UNSUPPORTED_FACT")
    if unsupported_path:
        errors.append("UNSUPPORTED_PATH")
    return QualityGateResult(
        "EVIDENCE_CITATION",
        not errors,
        errors,
        {
            "invalid_citation_count": invalid,
            "missing_citation_count": missing,
            "unsupported_fact_count": unsupported_fact,
            "unsupported_factual_path_count": unsupported_path,
        },
        errors,
    )


def _valid_citation(item) -> bool:
    span = item.source_span
    return bool(
        item.document_id
        and item.document_version_id
        and item.source_us_id
        and item.text_unit_id
        and isinstance(span.get("start"), int)
        and isinstance(span.get("end"), int)
        and span["end"] >= span["start"]
        and item.text_hash
        and item.evidence_excerpt
    )


def _impact_items(output: FunctionalQAResult | ImpactAnalysisResult):
    return [
        *getattr(output, "direct_impacts", []),
        *getattr(output, "indirect_impacts", []),
        *getattr(output, "tentative_impacts", []),
    ]
