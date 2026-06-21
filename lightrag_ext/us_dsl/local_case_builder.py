from __future__ import annotations

from .local_fullflow_types import LocalDiscoveredDocument, LocalEvaluationCase

_TASK_SEQUENCE = ["FACT_QA", "IMPACT_ANALYSIS", "HISTORICAL_COMPARE", "MIGRATION_ANALYSIS", "DESIGN_CONTEXT"]


def build_local_cases(documents: list[LocalDiscoveredDocument], *, minimum_case_count: int = 8) -> dict[str, list[LocalEvaluationCase]]:
    accepted = [doc for doc in documents if doc.accepted]
    gold_backed: list[LocalEvaluationCase] = []
    silver: list[LocalEvaluationCase] = []
    negative: list[LocalEvaluationCase] = []
    version: list[LocalEvaluationCase] = []
    for doc in accepted:
        if doc.role == "QUALITY_ANNOTATION":
            negative.append(_case(doc, "NEGATIVE_QUALITY", "DESIGN_CONTEXT", len(negative)))
        elif doc.role in {"SYNTHETIC_CHANGE_SET", "DFX_VARIANT"}:
            version.append(_case(doc, "VERSION_STRESS", "HISTORICAL_COMPARE", len(version)))
            version.append(_case(doc, "VERSION_STRESS", "MIGRATION_ANALYSIS", len(version)))
        else:
            for _ in range(max(doc.detected_us_count, 1)):
                silver.append(_case(doc, "SILVER_REGRESSION", _TASK_SEQUENCE[len(silver) % len(_TASK_SEQUENCE)], len(silver)))
    seed_docs = [doc for doc in accepted if doc.role != "QUALITY_ANNOTATION"] or accepted
    index = 0
    while seed_docs and (len(gold_backed) + len(silver) + len(negative) + len(version)) < minimum_case_count:
        doc = seed_docs[index % len(seed_docs)]
        silver.append(_case(doc, "SILVER_REGRESSION", _TASK_SEQUENCE[index % len(_TASK_SEQUENCE)], len(silver)))
        index += 1
    return {
        "gold_backed": gold_backed,
        "silver_regression": silver,
        "negative_quality": negative,
        "version_stress": version,
    }


def case_source_report(cases_by_set: dict[str, list[LocalEvaluationCase]]) -> dict[str, object]:
    return {
        "gold_backed_count": len(cases_by_set.get("gold_backed", [])),
        "silver_regression_count": len(cases_by_set.get("silver_regression", [])),
        "negative_quality_count": len(cases_by_set.get("negative_quality", [])),
        "version_stress_count": len(cases_by_set.get("version_stress", [])),
        "llm_generated_primary_gold_count": sum(
            1
            for cases in cases_by_set.values()
            for case in cases
            if case.generated_by_llm and case.primary_gold
        ),
    }


def _case(document: LocalDiscoveredDocument, case_set: str, task_type: str, index: int) -> LocalEvaluationCase:
    keyword = document.text_excerpt.split()[0] if document.text_excerpt.split() else document.file_name
    return LocalEvaluationCase(
        case_id=f"{case_set.lower()}-{document.document_id}-{index:03d}",
        document_id=document.document_id,
        case_set=case_set,  # type: ignore[arg-type]
        task_type=task_type,
        query=f"Locate explicit evidence for {document.file_name}",
        source_ref=document.path,
        text_unit_id=f"{document.document_id}:tu:{index:03d}",
        evidence_keywords=[keyword],
        relation_types=["LOCAL_EXPLICIT_RELATION"] if task_type == "IMPACT_ANALYSIS" else [],
        required_dimensions=["LOCAL_EXPLICIT_DIMENSION"] if task_type in {"IMPACT_ANALYSIS", "DESIGN_CONTEXT"} else [],
        valid=True,
        primary_gold=case_set == "GOLD_BACKED",
        generated_by_llm=False,
    )
