from __future__ import annotations

from lightrag_ext.us_dsl.evidence_path_validator import validate_evidence_paths
from lightrag_ext.us_dsl.hybrid_retrieval_types import PathCandidate


def test_evidence_complete_path_is_factual() -> None:
    path = PathCandidate("p1", ["a", "b"], ["r1"], evidence_refs=["e1"])
    report = validate_evidence_paths([path], task_type="FACT_QA")
    assert path.validation_status == "FACTUAL"
    assert report.missing_evidence_factual_path_count == 0


def test_missing_evidence_path_is_not_factual() -> None:
    path = PathCandidate("p1", ["a", "b"], ["r1"])
    validate_evidence_paths([path], task_type="FACT_QA")
    assert path.validation_status == "NOT_FACTUAL_MISSING_EVIDENCE"


def test_issue_edge_cannot_enter_factual_path() -> None:
    path = PathCandidate("p1", ["a", "b"], ["r1"], evidence_refs=["e1"], has_issue_edge=True)
    validate_evidence_paths([path], task_type="FACT_QA")
    assert path.validation_status == "NOT_FACTUAL_ISSUE_EDGE"


def test_version_conflict_path_is_tentative() -> None:
    path = PathCandidate("p1", ["a", "b"], ["r1"], evidence_refs=["e1"], version_conflict=True)
    validate_evidence_paths([path], task_type="FACT_QA")
    assert path.validation_status == "TENTATIVE_VERSION_CONFLICT"


def test_generic_path_is_background_only() -> None:
    path = PathCandidate("p1", ["a", "b"], ["r1"], evidence_refs=["e1"], generic_only=True)
    validate_evidence_paths([path], task_type="FACT_QA")
    assert path.validation_status == "BACKGROUND_ONLY"


def test_hop_limit_depends_on_task_type() -> None:
    fact_path = PathCandidate("p1", ["a", "b", "c", "d"], ["r1", "r2", "r3"], evidence_refs=["e1"])
    impact_path = PathCandidate("p2", ["a", "b", "c", "d"], ["r1", "r2", "r3"], evidence_refs=["e1"])
    validate_evidence_paths([fact_path], task_type="FACT_QA")
    validate_evidence_paths([impact_path], task_type="IMPACT_ANALYSIS")
    assert fact_path.validation_status == "INVALID_HOP_LIMIT"
    assert impact_path.validation_status == "FACTUAL"


def test_no_dangling_path() -> None:
    path = PathCandidate("p1", ["a"], ["r1"], dangling=True)
    validate_evidence_paths([path], task_type="FACT_QA")
    assert path.validation_status == "DANGLING_PATH"
