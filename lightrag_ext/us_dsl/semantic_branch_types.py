from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

SemanticObjectDisposition = Literal[
    "APPROVED_PFSS",
    "BLOCKED_ISSUE",
    "INFO_ONLY",
    "GENERIC_CANDIDATE",
    "DROPPED_INVALID",
]
SemanticRoute = Literal["DSL_FULL", "DSL_PARTIAL", "RAW_ONLY", "PARSE_FAILED"]
SourceReferenceStrategy = Literal[
    "EXISTING_CHUNK_REFERENCE",
    "IDEMPOTENT_CHUNK_REUSE",
    "EXTERNAL_SIDECAR_REFERENCE",
    "UNRESOLVED",
]


@dataclass(frozen=True)
class SemanticBranchExecutionConfig:
    enabled: bool = True
    execution_mode: Literal["PLAN_ONLY", "ISOLATED_TEST_WRITE"] = "ISOLATED_TEST_WRITE"
    artifact_root: str = "artifacts/block_24b2_semantic_branch_isolation"
    pfss_workspace: str = "block24b2_pfss_test"
    pfss_namespace: str = "pfss_test_graph"
    generic_workspace: str = "block24b2_generic_test"
    generic_namespace: str = "generic_test_graph"
    issue_index_path: str | None = None
    use_real_embedding: bool = False
    allow_generic_graph: bool = False
    cleanup_after_run: bool = False
    timeout_seconds: int = 120
    enforce_raw_evidence_success: bool = True
    enforce_no_llm: bool = True
    enforce_no_original_extraction: bool = True
    enforce_graph_isolation: bool = True


@dataclass(frozen=True)
class SemanticObject:
    object_id: str
    label: str
    object_type: str
    disposition: SemanticObjectDisposition
    source_id: str
    text_unit_id: str | None = None
    source_us_id: str | None = None
    source_span: dict[str, int] = field(default_factory=dict)
    text_hash: str | None = None
    evidence_text: str = ""
    domain_code: str | None = None
    feature_key: str | None = None
    issue_type: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class SemanticRelationship:
    relationship_id: str
    src_id: str
    tgt_id: str
    relationship_type: str
    disposition: SemanticObjectDisposition
    source_id: str
    evidence_text: str = ""
    issue_type: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class PfssPayload:
    document_id: str
    document_version_id: str
    semantic_route: SemanticRoute
    source_chunk_ids: list[str]
    safe_entities: list[SemanticObject]
    safe_relationships: list[SemanticRelationship]
    blocked_objects: list[SemanticObject] = field(default_factory=list)
    blocked_relationships: list[SemanticRelationship] = field(default_factory=list)
    sidecar_alignment_passed: bool = True
    endpoint_closure_passed: bool = True
    forbidden_relation_count: int = 0
    duplicate_id_count: int = 0
    dangling_relationship_count: int = 0


@dataclass(frozen=True)
class GraphIsolationSnapshot:
    pfss_node_ids: list[str] = field(default_factory=list)
    pfss_edge_ids: list[str] = field(default_factory=list)
    generic_node_ids: list[str] = field(default_factory=list)
    generic_edge_ids: list[str] = field(default_factory=list)
    issue_object_ids: list[str] = field(default_factory=list)
    pfss_generic_node_overlap_count: int = 0
    pfss_generic_edge_overlap_count: int = 0
    pfss_issue_overlap_count: int = 0
    namespace_collision_count: int = 0


@dataclass(frozen=True)
class SemanticBranchExecutionResult:
    trace_id: str
    document_id: str
    document_version_id: str
    semantic_route: SemanticRoute
    raw_evidence_status: str
    dsl_compile_executed: bool
    pfss_write_executed: bool
    generic_write_executed: bool
    issue_index_write_executed: bool
    safe_chunk_count: int
    safe_entity_count: int
    safe_relationship_count: int
    blocked_object_count: int
    issue_record_count: int
    pfss_graph_node_count: int
    pfss_graph_edge_count: int
    generic_graph_node_count: int
    generic_graph_edge_count: int
    pfss_entity_vector_count: int
    pfss_relationship_vector_count: int
    duplicate_semantic_object_count: int
    cross_space_collision_count: int
    extract_entities_called: bool
    gleaning_executed: bool
    llm_called: bool
    embedding_called: bool
    source_reference_strategy: SourceReferenceStrategy
    raw_chunk_count_before: int
    raw_chunk_count_after: int
    raw_chunk_vector_count_before: int
    raw_chunk_vector_count_after: int
    duplicate_raw_chunk_count: int
    sidecar_alignment_passed: bool
    endpoint_closure_passed: bool
    forbidden_relation_count: int
    dangling_relationship_count: int
    status: str
    issues: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticBranchSuiteResult:
    results: list[SemanticBranchExecutionResult]
    graph_isolation_snapshot: GraphIsolationSnapshot
    source_reference_strategy: SourceReferenceStrategy
    safety_check: dict[str, bool]
    idempotency_passed: bool
    cleanup_passed: bool
    unresolved_questions: list[str] = field(default_factory=list)

    def report(self) -> dict[str, Any]:
        sidecar_alignment_passed = all(r.sidecar_alignment_passed for r in self.results)
        endpoint_closure_passed = all(r.endpoint_closure_passed for r in self.results)
        forbidden_relation_count = sum(r.forbidden_relation_count for r in self.results)
        duplicate_semantic_object_count = sum(r.duplicate_semantic_object_count for r in self.results)
        return {
            "block": "24B-2",
            "result_count": len(self.results),
            "dsl_full_pfss_write": any(r.semantic_route == "DSL_FULL" and r.pfss_write_executed for r in self.results),
            "dsl_partial_pfss_write": any(r.semantic_route == "DSL_PARTIAL" and r.pfss_write_executed for r in self.results),
            "dsl_partial_issue_write": any(r.semantic_route == "DSL_PARTIAL" and r.issue_index_write_executed for r in self.results),
            "raw_only_pfss_write": any(r.semantic_route == "RAW_ONLY" and r.pfss_write_executed for r in self.results),
            "parse_failed_semantic_write": any(
                r.semantic_route == "PARSE_FAILED"
                and (r.pfss_write_executed or r.generic_write_executed or r.issue_index_write_executed)
                for r in self.results
            ),
            "source_reference_strategy": self.source_reference_strategy,
            "sidecar_alignment_passed": sidecar_alignment_passed,
            "endpoint_closure_passed": endpoint_closure_passed,
            "forbidden_relation_count": forbidden_relation_count,
            "duplicate_semantic_object_count": duplicate_semantic_object_count,
            "issue_object_written_to_pfss_count": self.graph_isolation_snapshot.pfss_issue_overlap_count,
            "artifacts_complete": False,
            "real_embedding_smoke_executed": False,
            "real_embedding_smoke_status": "NOT_RUN",
            "real_embedding_smoke_passed": None,
            "graph_isolation_snapshot": to_plain_dict(self.graph_isolation_snapshot),
            "safety_check": self.safety_check,
            "idempotency_passed": self.idempotency_passed,
            "cleanup_passed": self.cleanup_passed,
            "results": [to_plain_dict(r) for r in self.results],
            "unresolved_questions": self.unresolved_questions,
        }


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
