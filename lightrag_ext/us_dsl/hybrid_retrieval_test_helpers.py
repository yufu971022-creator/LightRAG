from __future__ import annotations

from .hybrid_retrieval_types import EvidenceRef, HybridRetrievalRequest, PathCandidate, RetrievalCandidate
from .hybrid_retrieval_service import HybridRetrievalService, InMemoryHybridRetrievalStore


def evidence(
    doc: str = "doc-a",
    version: str = "v1",
    unit: str = "u1",
    start: int = 0,
    end: int = 20,
    text_hash: str = "hash-a",
    excerpt: str = "direct evidence",
) -> EvidenceRef:
    return EvidenceRef(
        document_id=doc,
        document_version_id=version,
        text_unit_id=unit,
        source_span={"start": start, "end": end},
        text_hash=text_hash,
        excerpt=excerpt,
    )


def build_fixture_store() -> InMemoryHybridRetrievalStore:
    ev1 = evidence(excerpt="Primary direct evidence for current rule")
    ev2 = evidence(doc="doc-a", version="v1", unit="u2", start=21, end=50, text_hash="hash-b")
    factual_path = PathCandidate(
        path_id="path-factual",
        node_ids=["obj-source", "obj-target"],
        edge_ids=["rel-1"],
        evidence_refs=["doc-a:v1:u1"],
    )
    tentative_path = PathCandidate(
        path_id="path-version-conflict",
        node_ids=["obj-source", "obj-old"],
        edge_ids=["rel-old"],
        evidence_refs=["doc-a:v1:u2"],
        version_conflict=True,
    )
    generic_path = PathCandidate(
        path_id="path-generic",
        node_ids=["gen-a", "gen-b"],
        edge_ids=["gen-rel"],
        generic_only=True,
    )
    dangling_path = PathCandidate(
        path_id="path-dangling",
        node_ids=["dangling-a"],
        edge_ids=["dangling-rel"],
        dangling=True,
    )
    raw = [
        RetrievalCandidate(
            candidate_id="raw-current",
            channel="RAW_TEXT",
            kind="TEXT",
            text="Current direct evidence for the requested rule.",
            raw_score=0.91,
            source="raw_store",
            trust_tier="T1_DIRECT",
            stable_identity_key="identity:rule-main",
            evidence=[ev1],
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="rule",
        ),
        RetrievalCandidate(
            candidate_id="raw-deleted",
            channel="RAW_TEXT",
            kind="TEXT",
            text="Deleted content should not appear in active projection.",
            raw_score=0.99,
            source="raw_store",
            trust_tier="T1_DIRECT",
            evidence=[evidence(doc="doc-z", version="v0", unit="u0", text_hash="deleted")],
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="rule",
            deleted=True,
        ),
        RetrievalCandidate(
            candidate_id="raw-historical",
            channel="RAW_TEXT",
            kind="TEXT",
            text="Historical evidence kept only when requested.",
            raw_score=0.52,
            source="raw_store",
            trust_tier="T1_DIRECT",
            evidence=[evidence(doc="doc-h", version="v0", unit="u1", text_hash="hash-h")],
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="rule",
            active=False,
        ),
    ]
    pfss = [
        RetrievalCandidate(
            candidate_id="pfss-entity-main",
            channel="PFSS_ENTITY",
            kind="ENTITY",
            text="Semantic object describing the requested rule.",
            raw_score=0.88,
            source="pfss_graph",
            trust_tier="T2_SEMANTIC",
            semantic_object_id="obj-source",
            stable_identity_key="identity:rule-main",
            evidence=[ev1],
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="rule",
        ),
        RetrievalCandidate(
            candidate_id="pfss-relation-main",
            channel="PFSS_RELATION",
            kind="RELATION",
            text="Semantic relation supporting impact path.",
            raw_score=0.86,
            source="pfss_graph",
            trust_tier="T2_SEMANTIC",
            semantic_relation_id="rel-1",
            evidence=[ev2],
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="relation",
        ),
        RetrievalCandidate(
            candidate_id="pfss-path-main",
            channel="PFSS_PATH",
            kind="PATH",
            text="Evidence-backed path from source to target.",
            raw_score=0.84,
            source="pfss_graph",
            trust_tier="T2_SEMANTIC",
            path=factual_path,
            evidence=[ev1, ev2],
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="path",
        ),
        RetrievalCandidate(
            candidate_id="pfss-path-version-warning",
            channel="PFSS_PATH",
            kind="PATH",
            text="Tentative path with version warning.",
            raw_score=0.7,
            source="pfss_graph",
            trust_tier="T3_TENTATIVE",
            path=tentative_path,
            evidence=[ev2],
            version_status="CONFLICT",
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="path",
        ),
        RetrievalCandidate(
            candidate_id="pfss-missing-evidence",
            channel="PFSS_ENTITY",
            kind="ENTITY",
            text="Semantic object without direct evidence.",
            raw_score=0.42,
            source="pfss_graph",
            trust_tier="T3_TENTATIVE",
            semantic_object_id="obj-missing",
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="rule",
        ),
        RetrievalCandidate(
            candidate_id="pfss-dangling-path",
            channel="PFSS_PATH",
            kind="PATH",
            text="Invalid dangling path.",
            raw_score=0.35,
            source="pfss_graph",
            trust_tier="T3_TENTATIVE",
            path=dangling_path,
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="path",
        ),
    ]
    generic = [
        RetrievalCandidate(
            candidate_id="generic-duplicate",
            channel="GENERIC_GRAPH",
            kind="ENTITY",
            text="Low-trust background duplicate.",
            raw_score=0.97,
            source="generic_graph",
            trust_tier="T4_BACKGROUND",
            factual_weight=0.2,
            stable_identity_key="identity:rule-main",
            semantic_object_id="obj-source",
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="rule",
        ),
        RetrievalCandidate(
            candidate_id="generic-background",
            channel="GENERIC_GRAPH",
            kind="PATH",
            text="Background-only generic path.",
            raw_score=0.62,
            source="generic_graph",
            trust_tier="T4_BACKGROUND",
            factual_weight=0.2,
            path=generic_path,
            domain_code="domain-a",
            feature_key="feature-a",
            object_type="path",
        ),
    ]
    issues = [
        RetrievalCandidate(
            candidate_id="issue-version-conflict",
            channel="ISSUE_SIDECAR",
            kind="ISSUE",
            text="Version conflict warning for review.",
            raw_score=0.8,
            source="sidecar",
            trust_tier="T5_WARNING",
            factual_weight=0.0,
            issue_type="VERSION_CONFLICT",
            severity="HIGH",
            domain_code="domain-a",
            feature_key="feature-a",
        ),
        RetrievalCandidate(
            candidate_id="version-context",
            channel="VERSION_CONTEXT",
            kind="VERSION",
            text="Current and historical version context.",
            raw_score=0.75,
            source="sidecar",
            trust_tier="T5_WARNING",
            factual_weight=0.0,
            version_intent="COMPARE",
            domain_code="domain-a",
            feature_key="feature-a",
        ),
    ]
    return InMemoryHybridRetrievalStore(raw, pfss, generic, issues)


def build_service() -> HybridRetrievalService:
    return HybridRetrievalService(build_fixture_store())


def default_request(**overrides: object) -> HybridRetrievalRequest:
    values = {
        "query_text": "current rule impact",
        "task_type": "FACT_QA",
        "domain_code": "domain-a",
        "feature_key": "feature-a",
        "object_type": "rule",
        "top_k": 12,
    }
    values.update(overrides)
    return HybridRetrievalRequest(**values)  # type: ignore[arg-type]
