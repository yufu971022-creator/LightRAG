from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .graph_space_policy import GraphSpaceDescriptor, GraphSpacePolicyError, validate_graph_space_descriptor
from .semantic_branch_types import PfssPayload, SourceReferenceStrategy

PFSS_ALLOWED_TYPES = {
    "FeatureCatalog",
    "DomainObject",
    "FieldSpec",
    "RuleAtom",
    "TaskRule",
    "StateTransition",
    "IntegrationEndpoint",
    "ReportSpec",
    "RolePermission",
    "DataMigrationSpec",
    "RuleVersion",
    "CanonicalTerm",
}
FORBIDDEN_RELATION_TYPES = {
    "ReviewRequired",
    "InfoOnly",
    "VersionReviewRequired",
    "VersionConflictWith",
    "MissingEvidence",
    "InvalidType",
    "InvalidRelation",
    "ForbiddenRelation",
    "DanglingRelationship",
}
FINAL_FORBIDDEN_RELATION_TYPES = {
    "has_child",
    "belongs_to",
    "references_to",
    "queries_from",
    "queries_by",
    "contains",
    "related_to",
}
ISSUE_OBJECT_TYPES = {
    "VERSION_REVIEW_REQUIRED",
    "VERSION_CONFLICT",
    "MISSING_EVIDENCE",
    "INVALID_TYPE",
    "INVALID_RELATION",
    "DANGLING_RELATIONSHIP",
    "TERM_AMBIGUITY",
    "REVIEW_REQUIRED",
    "INFO_ONLY",
    "VersionReviewRequired",
    "VersionConflictWith",
    "MissingEvidence",
    "InvalidType",
    "InvalidRelation",
    "DanglingRelationship",
    "TermAmbiguity",
    "ReviewRequired",
    "InfoOnly",
}
SOURCE_REFERENCE_STRATEGY: SourceReferenceStrategy = "EXTERNAL_SIDECAR_REFERENCE"


@dataclass(frozen=True)
class PfssSourceReferenceReport:
    strategy: SourceReferenceStrategy
    raw_chunk_count_before: int
    raw_chunk_count_after: int
    raw_chunk_vector_count_before: int
    raw_chunk_vector_count_after: int
    duplicate_raw_chunk_count: int


@dataclass(frozen=True)
class PfssGraphWriteResult:
    pfss_write_executed: bool
    node_count: int
    edge_count: int
    entity_vector_count: int
    relationship_vector_count: int
    duplicate_semantic_object_count: int
    source_reference_report: PfssSourceReferenceReport
    sidecar_alignment_passed: bool
    endpoint_closure_passed: bool
    forbidden_relation_count: int
    dangling_relationship_count: int
    status: str
    issues: list[str] = field(default_factory=list)


def write_pfss_graph(
    *,
    payload: PfssPayload,
    descriptor: GraphSpaceDescriptor,
    artifact_root: str,
    raw_chunk_count_before: int,
    raw_chunk_vector_count_before: int,
) -> PfssGraphWriteResult:
    issues = validate_pfss_payload(payload, descriptor)
    source_report = PfssSourceReferenceReport(
        strategy=SOURCE_REFERENCE_STRATEGY,
        raw_chunk_count_before=raw_chunk_count_before,
        raw_chunk_count_after=raw_chunk_count_before,
        raw_chunk_vector_count_before=raw_chunk_vector_count_before,
        raw_chunk_vector_count_after=raw_chunk_vector_count_before,
        duplicate_raw_chunk_count=0,
    )
    if issues:
        return PfssGraphWriteResult(
            pfss_write_executed=False,
            node_count=0,
            edge_count=0,
            entity_vector_count=0,
            relationship_vector_count=0,
            duplicate_semantic_object_count=payload.duplicate_id_count,
            source_reference_report=source_report,
            sidecar_alignment_passed=payload.sidecar_alignment_passed,
            endpoint_closure_passed=payload.endpoint_closure_passed,
            forbidden_relation_count=payload.forbidden_relation_count,
            dangling_relationship_count=payload.dangling_relationship_count,
            status="BLOCKED",
            issues=issues,
        )
    root = _space_root(artifact_root, descriptor)
    graph = _load_graph(root)
    sidecar = _load_sidecar(root)
    for entity in payload.safe_entities:
        graph["nodes"][entity.object_id] = {
            "id": entity.object_id,
            "label": entity.label,
            "type": entity.object_type,
            "source_id": entity.source_id,
            "document_id": payload.document_id,
            "document_version_id": payload.document_version_id,
            "evidence_text": entity.evidence_text,
            "domain_code": entity.domain_code,
            "feature_key": entity.feature_key,
            "graph_space": "PFSS",
            "sidecar_id": _sidecar_id(entity.object_id),
        }
        sidecar[_sidecar_id(entity.object_id)] = _sidecar_record(
            graph_object_id=entity.object_id,
            object_kind="entity",
            source_id=entity.source_id,
            document_id=payload.document_id,
            document_version_id=payload.document_version_id,
        )
    for relation in payload.safe_relationships:
        graph["edges"][relation.relationship_id] = {
            "id": relation.relationship_id,
            "src_id": relation.src_id,
            "tgt_id": relation.tgt_id,
            "type": relation.relationship_type,
            "source_id": relation.source_id,
            "document_id": payload.document_id,
            "document_version_id": payload.document_version_id,
            "evidence_text": relation.evidence_text,
            "graph_space": "PFSS",
            "sidecar_id": _sidecar_id(relation.relationship_id),
        }
        sidecar[_sidecar_id(relation.relationship_id)] = _sidecar_record(
            graph_object_id=relation.relationship_id,
            object_kind="relationship",
            source_id=relation.source_id,
            document_id=payload.document_id,
            document_version_id=payload.document_version_id,
        )
    _write_graph(root, graph)
    _write_sidecar(root, sidecar)
    _write_vector_index(root / "entities_vdb.json", graph["nodes"])
    _write_vector_index(root / "relationships_vdb.json", graph["edges"])
    return PfssGraphWriteResult(
        pfss_write_executed=True,
        node_count=len(graph["nodes"]),
        edge_count=len(graph["edges"]),
        entity_vector_count=len(graph["nodes"]),
        relationship_vector_count=len(graph["edges"]),
        duplicate_semantic_object_count=payload.duplicate_id_count,
        source_reference_report=source_report,
        sidecar_alignment_passed=True,
        endpoint_closure_passed=True,
        forbidden_relation_count=0,
        dangling_relationship_count=0,
        status="WRITTEN",
        issues=[],
    )


def validate_pfss_payload(payload: PfssPayload, descriptor: GraphSpaceDescriptor) -> list[str]:
    issues: list[str] = []
    try:
        validate_graph_space_descriptor(descriptor)
    except GraphSpacePolicyError as exc:
        issues.append(str(exc))
    if payload.semantic_route not in {"DSL_FULL", "DSL_PARTIAL"}:
        issues.append("route_not_pfss_eligible")
    if not payload.safe_entities and not payload.safe_relationships:
        issues.append("empty_safe_pfss_payload")
    if not payload.sidecar_alignment_passed:
        issues.append("sidecar_alignment_failed")
    if not payload.endpoint_closure_passed:
        issues.append("endpoint_closure_failed")
    if payload.forbidden_relation_count:
        issues.append("forbidden_relation_count_nonzero")
    if payload.duplicate_id_count:
        issues.append("duplicate_id_count_nonzero")
    safe_ids = {entity.object_id for entity in payload.safe_entities}
    if len(safe_ids) != len(payload.safe_entities):
        issues.append("duplicate_entity_ids")
    for entity in payload.safe_entities:
        if entity.object_type not in PFSS_ALLOWED_TYPES:
            issues.append(f"invalid_pfss_type:{entity.object_type}")
        if entity.disposition != "APPROVED_PFSS":
            issues.append(f"non_approved_entity:{entity.object_id}")
        if entity.source_id not in payload.source_chunk_ids:
            issues.append(f"missing_sidecar_source:{entity.object_id}")
    for relation in payload.safe_relationships:
        if relation.relationship_type in FORBIDDEN_RELATION_TYPES:
            issues.append(f"forbidden_relation:{relation.relationship_id}")
        if relation.disposition != "APPROVED_PFSS":
            issues.append(f"non_approved_relation:{relation.relationship_id}")
        if relation.src_id not in safe_ids or relation.tgt_id not in safe_ids:
            issues.append(f"dangling_relationship:{relation.relationship_id}")
        if relation.source_id not in payload.source_chunk_ids:
            issues.append(f"missing_sidecar_source:{relation.relationship_id}")
    return sorted(set(issues))


def snapshot_pfss_graph(*, descriptor: GraphSpaceDescriptor, artifact_root: str) -> dict[str, Any]:
    root = _space_root(artifact_root, descriptor)
    graph = _load_graph(root)
    sidecar = _load_sidecar(root)
    return {
        "workspace": descriptor.workspace,
        "namespace": descriptor.namespace,
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "entity_vector_count": _json_count(root / "entities_vdb.json"),
        "relationship_vector_count": _json_count(root / "relationships_vdb.json"),
        "node_ids": sorted(graph["nodes"]),
        "edge_ids": sorted(graph["edges"]),
        "sidecar_count": len(sidecar),
        "sidecar_ids": sorted(sidecar),
        "sidecar_alignment_passed": validate_sidecar_alignment(descriptor=descriptor, artifact_root=artifact_root),
        "endpoint_closure_passed": validate_endpoint_closure(descriptor=descriptor, artifact_root=artifact_root),
        "forbidden_relation_count": forbidden_relation_count(descriptor=descriptor, artifact_root=artifact_root),
        "duplicate_semantic_object_count": duplicate_semantic_object_count(descriptor=descriptor, artifact_root=artifact_root),
        "issue_object_written_to_pfss_count": issue_object_written_to_pfss_count(descriptor=descriptor, artifact_root=artifact_root),
    }


def validate_sidecar_alignment(*, descriptor: GraphSpaceDescriptor, artifact_root: str) -> bool:
    root = _space_root(artifact_root, descriptor)
    graph = _load_graph(root)
    sidecar = _load_sidecar(root)
    graph_ids = set(graph["nodes"]) | set(graph["edges"])
    sidecar_graph_ids = {record.get("graph_object_id") for record in sidecar.values()}
    if graph_ids != sidecar_graph_ids:
        return False
    for graph_id in graph_ids:
        graph_object = graph["nodes"].get(graph_id) or graph["edges"].get(graph_id)
        sidecar_id = graph_object.get("sidecar_id")
        if not sidecar_id or sidecar_id not in sidecar:
            return False
        if sidecar[sidecar_id].get("graph_object_id") != graph_id:
            return False
    return True


def validate_endpoint_closure(*, descriptor: GraphSpaceDescriptor, artifact_root: str) -> bool:
    graph = _load_graph(_space_root(artifact_root, descriptor))
    node_ids = set(graph["nodes"])
    return all(edge.get("src_id") in node_ids and edge.get("tgt_id") in node_ids for edge in graph["edges"].values())


def forbidden_relation_count(*, descriptor: GraphSpaceDescriptor, artifact_root: str) -> int:
    graph = _load_graph(_space_root(artifact_root, descriptor))
    return sum(1 for edge in graph["edges"].values() if str(edge.get("type", "")).lower() in FINAL_FORBIDDEN_RELATION_TYPES)


def duplicate_semantic_object_count(*, descriptor: GraphSpaceDescriptor, artifact_root: str) -> int:
    graph = _load_graph(_space_root(artifact_root, descriptor))
    ids = list(graph["nodes"]) + list(graph["edges"])
    return len(ids) - len(set(ids))


def issue_object_written_to_pfss_count(*, descriptor: GraphSpaceDescriptor, artifact_root: str) -> int:
    graph = _load_graph(_space_root(artifact_root, descriptor))
    return sum(1 for node in graph["nodes"].values() if str(node.get("type")) in ISSUE_OBJECT_TYPES)


def _space_root(artifact_root: str, descriptor: GraphSpaceDescriptor) -> Path:
    root = Path(artifact_root) / "workspaces" / descriptor.workspace / descriptor.namespace
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_graph(root: Path) -> dict[str, Any]:
    path = root / "graph.json"
    if not path.exists():
        return {"nodes": {}, "edges": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_sidecar(root: Path) -> dict[str, Any]:
    path = root / "sidecar.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_graph(root: Path, graph: dict[str, Any]) -> None:
    (root / "graph.json").write_text(json.dumps(graph, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_sidecar(root: Path, sidecar: dict[str, Any]) -> None:
    (root / "sidecar.json").write_text(json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _sidecar_id(graph_object_id: str) -> str:
    return f"sidecar:{graph_object_id}"


def _sidecar_record(
    *,
    graph_object_id: str,
    object_kind: str,
    source_id: str,
    document_id: str,
    document_version_id: str,
) -> dict[str, Any]:
    return {
        "sidecar_id": _sidecar_id(graph_object_id),
        "graph_object_id": graph_object_id,
        "object_kind": object_kind,
        "source_id": source_id,
        "document_id": document_id,
        "document_version_id": document_version_id,
        "reverse_locator": {"graph_object_id": graph_object_id, "graph_space": "PFSS"},
    }


def _write_vector_index(path: Path, records: dict[str, Any]) -> None:
    path.write_text(json.dumps({key: {"id": key} for key in sorted(records)}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _json_count(path: Path) -> int:
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return len(data) if isinstance(data, dict) else 0
