from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

DocumentVersionStatus = Literal[
    "STAGED",
    "ACTIVE",
    "SUPERSEDED",
    "DELETED",
    "REBUILD_REQUIRED",
    "REBUILDING",
    "FAILED",
]
LifecycleOperationType = Literal[
    "UPSERT_NEW_VERSION",
    "DELETE_DOCUMENT_VERSION",
    "DELETE_LOGICAL_DOCUMENT",
    "REBUILD_DOCUMENT_VERSION",
]
LifecycleMutationStatus = Literal[
    "PLANNED",
    "APPLYING",
    "APPLIED",
    "COMPENSATING",
    "COMPENSATED",
    "FAILED",
]
MutationStepStatus = Literal["PENDING", "APPLIED", "SKIPPED", "COMPENSATED", "FAILED"]
StoreKind = Literal["SIDECAR", "RAW_KV", "VECTOR", "PFSS_GRAPH", "VALIDATION", "ISSUE_INDEX"]

EXTERNAL_STORE_KINDS = {"RAW_KV", "VECTOR", "PFSS_GRAPH"}


@dataclass(frozen=True)
class LifecycleDocumentBundle:
    document: dict[str, Any]
    document_version: dict[str, Any]
    raw_chunks: list[dict[str, Any]] = field(default_factory=list)
    source_text_units: list[dict[str, Any]] = field(default_factory=list)
    chunk_text_unit_links: list[dict[str, Any]] = field(default_factory=list)
    semantic_objects: list[dict[str, Any]] = field(default_factory=list)
    semantic_relations: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)

    @property
    def document_id(self) -> str:
        return str(self.document["document_id"])

    @property
    def document_version_id(self) -> str:
        return str(self.document_version["document_version_id"])


@dataclass(frozen=True)
class DiffItem:
    stable_id: str
    old: dict[str, Any] | None = None
    new: dict[str, Any] | None = None
    old_hash: str | None = None
    new_hash: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class DocumentVersionDiff:
    old_document_version_id: str | None
    new_document_version_id: str | None
    document_id: str
    content_changed: bool
    added_chunks: list[DiffItem] = field(default_factory=list)
    unchanged_chunks: list[DiffItem] = field(default_factory=list)
    updated_chunks: list[DiffItem] = field(default_factory=list)
    removed_chunks: list[DiffItem] = field(default_factory=list)
    added_text_units: list[DiffItem] = field(default_factory=list)
    unchanged_text_units: list[DiffItem] = field(default_factory=list)
    updated_text_units: list[DiffItem] = field(default_factory=list)
    removed_text_units: list[DiffItem] = field(default_factory=list)
    added_semantic_objects: list[DiffItem] = field(default_factory=list)
    unchanged_semantic_objects: list[DiffItem] = field(default_factory=list)
    updated_semantic_objects: list[DiffItem] = field(default_factory=list)
    removed_semantic_objects: list[DiffItem] = field(default_factory=list)
    added_semantic_relations: list[DiffItem] = field(default_factory=list)
    unchanged_semantic_relations: list[DiffItem] = field(default_factory=list)
    updated_semantic_relations: list[DiffItem] = field(default_factory=list)
    removed_semantic_relations: list[DiffItem] = field(default_factory=list)
    opened_issues: list[DiffItem] = field(default_factory=list)
    unchanged_issues: list[DiffItem] = field(default_factory=list)
    resolved_issues: list[DiffItem] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.content_changed,
                self.added_chunks,
                self.updated_chunks,
                self.removed_chunks,
                self.added_text_units,
                self.updated_text_units,
                self.removed_text_units,
                self.added_semantic_objects,
                self.updated_semantic_objects,
                self.removed_semantic_objects,
                self.added_semantic_relations,
                self.updated_semantic_relations,
                self.removed_semantic_relations,
                self.opened_issues,
                self.resolved_issues,
            ]
        )


@dataclass(frozen=True)
class LifecycleStorageCapabilities:
    kv_upsert: bool
    kv_delete: bool
    vector_upsert: bool
    vector_delete: bool
    graph_node_upsert: bool
    graph_edge_upsert: bool
    graph_edge_delete: bool
    graph_node_delete: bool
    graph_readback: bool
    supports_safe_document_delete: bool
    unsupported_operations: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    blocked_by_core_gap: bool = False
    direct_storage_file_edit_used: bool = False


@dataclass(frozen=True)
class MutationOperation:
    operation_id: str
    operation_kind: str
    store_kind: StoreKind
    target_kind: str
    target_id: str
    reason: str
    precondition: str
    preimage: dict[str, Any] | None
    postimage: dict[str, Any] | None
    compensation_operation: str | None
    order: int


@dataclass(frozen=True)
class MutationPlan:
    mutation_id: str
    operation_type: LifecycleOperationType
    document_id: str
    old_document_version_id: str | None
    new_document_version_id: str | None
    operations: list[MutationOperation]
    plan_hash: str

    @property
    def external_write_operations(self) -> list[MutationOperation]:
        return [op for op in self.operations if op.store_kind in EXTERNAL_STORE_KINDS]


@dataclass(frozen=True)
class LifecycleMutationResult:
    mutation_id: str
    operation_type: LifecycleOperationType
    status: str
    plan_hash: str
    applied_step_count: int
    compensated_step_count: int
    error_code: str | None = None
    error_summary: str | None = None


@dataclass(frozen=True)
class IncrementalEmbeddingReport:
    embedding_input_count: int
    embedding_reused_count: int
    embedding_recomputed_count: int
    expected_recomputed_count: int
    passed: bool


@dataclass(frozen=True)
class CrossStoreValidationReport:
    active_version_pointer_correct: bool
    raw_projection_matches_sidecar: bool
    vector_projection_matches_sidecar: bool
    pfss_projection_matches_sidecar: bool
    dangling_edge_count: int
    orphan_vector_count: int
    duplicate_projection_count: int
    issue_object_written_to_pfss_count: int
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
