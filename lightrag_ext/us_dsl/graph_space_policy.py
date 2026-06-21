from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class GraphSpace(str, Enum):
    PFSS = "PFSS"
    GENERIC = "GENERIC"
    ISSUE = "ISSUE"


class GraphSpaceWriteMode(str, Enum):
    DISABLED = "DISABLED"
    ISOLATED_TEST_WRITE = "ISOLATED_TEST_WRITE"
    FUTURE_LIVE_WRITE = "FUTURE_LIVE_WRITE"


@dataclass(frozen=True)
class GraphSpaceDescriptor:
    space: GraphSpace
    workspace: str
    namespace: str
    graph_storage_type: str = "LOCAL_JSON_GRAPH"
    entity_vector_namespace: str | None = None
    relationship_vector_namespace: str | None = None
    shared_raw_evidence_reference: bool = True
    write_enabled: bool = False
    production_allowed: bool = False
    write_mode: GraphSpaceWriteMode = GraphSpaceWriteMode.DISABLED


class GraphSpacePolicyError(ValueError):
    pass


def pfss_descriptor(workspace: str = "block24b2_pfss_test", namespace: str = "pfss_test_graph") -> GraphSpaceDescriptor:
    return GraphSpaceDescriptor(
        space=GraphSpace.PFSS,
        workspace=workspace,
        namespace=namespace,
        entity_vector_namespace=f"{namespace}_entities_vdb",
        relationship_vector_namespace=f"{namespace}_relationships_vdb",
        write_enabled=True,
        write_mode=GraphSpaceWriteMode.ISOLATED_TEST_WRITE,
    )


def generic_descriptor(workspace: str = "block24b2_generic_test", namespace: str = "generic_test_graph", *, write_enabled: bool = False) -> GraphSpaceDescriptor:
    return GraphSpaceDescriptor(
        space=GraphSpace.GENERIC,
        workspace=workspace,
        namespace=namespace,
        entity_vector_namespace=f"{namespace}_entities_vdb",
        relationship_vector_namespace=f"{namespace}_relationships_vdb",
        write_enabled=write_enabled,
        write_mode=GraphSpaceWriteMode.ISOLATED_TEST_WRITE if write_enabled else GraphSpaceWriteMode.DISABLED,
    )


def issue_descriptor(workspace: str = "block24b2_issue_test", namespace: str = "issue_test_index") -> GraphSpaceDescriptor:
    return GraphSpaceDescriptor(
        space=GraphSpace.ISSUE,
        workspace=workspace,
        namespace=namespace,
        graph_storage_type="LOCAL_JSON_INDEX",
        entity_vector_namespace=None,
        relationship_vector_namespace=None,
        write_enabled=True,
        write_mode=GraphSpaceWriteMode.ISOLATED_TEST_WRITE,
    )


def validate_graph_space_descriptor(descriptor: GraphSpaceDescriptor) -> None:
    if descriptor.write_mode == GraphSpaceWriteMode.FUTURE_LIVE_WRITE:
        raise GraphSpacePolicyError("FUTURE_LIVE_WRITE is not allowed in Block 24B-2")
    if descriptor.production_allowed:
        raise GraphSpacePolicyError("production_allowed must be false in Block 24B-2")
    marker = f"{descriptor.workspace}:{descriptor.namespace}".lower()
    if descriptor.space == GraphSpace.PFSS:
        if "pfss_test" not in marker and "dsl_test" not in marker:
            raise GraphSpacePolicyError("PFSS workspace/namespace must contain pfss_test or dsl_test")
    if descriptor.space == GraphSpace.GENERIC:
        if "generic_test" not in marker:
            raise GraphSpacePolicyError("GENERIC workspace/namespace must contain generic_test")
    if descriptor.space == GraphSpace.ISSUE:
        if "pfss" in descriptor.namespace.lower() or "pfss" in descriptor.workspace.lower():
            raise GraphSpacePolicyError("ISSUE space must not use PFSS graph namespace")


def validate_graph_space_isolation(descriptors: list[GraphSpaceDescriptor]) -> None:
    seen: dict[tuple[str, str], GraphSpace] = {}
    for descriptor in descriptors:
        key = (descriptor.workspace, descriptor.namespace)
        prior = seen.get(key)
        if prior and prior != descriptor.space:
            raise GraphSpacePolicyError("FAIL_GRAPH_SPACE_COLLISION")
        seen[key] = descriptor.space
    for descriptor in descriptors:
        validate_graph_space_descriptor(descriptor)


def namespace_collision_count(descriptors: list[GraphSpaceDescriptor]) -> int:
    count = 0
    keys: dict[tuple[str, str], GraphSpace] = {}
    for descriptor in descriptors:
        key = (descriptor.workspace, descriptor.namespace)
        prior = keys.get(key)
        if prior and prior != descriptor.space:
            count += 1
        keys[key] = descriptor.space
    return count


def serialize_descriptors(descriptors: list[GraphSpaceDescriptor]) -> list[dict[str, Any]]:
    return [
        {
            "space": item.space.value,
            "workspace": item.workspace,
            "namespace": item.namespace,
            "graph_storage_type": item.graph_storage_type,
            "entity_vector_namespace": item.entity_vector_namespace,
            "relationship_vector_namespace": item.relationship_vector_namespace,
            "shared_raw_evidence_reference": item.shared_raw_evidence_reference,
            "write_enabled": item.write_enabled,
            "production_allowed": item.production_allowed,
            "write_mode": item.write_mode.value,
        }
        for item in descriptors
    ]
