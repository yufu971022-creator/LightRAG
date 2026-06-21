from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .graph_space_policy import GraphSpaceDescriptor, validate_graph_space_descriptor

SYNTHETIC_GENERIC_NODE_ID = "generic:Synthetic Generic Topic"


def write_synthetic_generic_graph(*, descriptor: GraphSpaceDescriptor, artifact_root: str) -> dict[str, Any]:
    validate_graph_space_descriptor(descriptor)
    root = _space_root(artifact_root, descriptor)
    graph = _load_graph(root)
    graph["nodes"][SYNTHETIC_GENERIC_NODE_ID] = {
        "id": SYNTHETIC_GENERIC_NODE_ID,
        "label": "Synthetic Generic Topic",
        "type": "GenericEntity",
        "description": "Synthetic graph-space isolation fixture only",
        "source_id": "GENERIC-SMOKE-001",
        "graph_space": "GENERIC",
    }
    _write_graph(root, graph)
    return snapshot_generic_graph(descriptor=descriptor, artifact_root=artifact_root)


def snapshot_generic_graph(*, descriptor: GraphSpaceDescriptor, artifact_root: str) -> dict[str, Any]:
    root = _space_root(artifact_root, descriptor)
    graph = _load_graph(root)
    return {
        "workspace": descriptor.workspace,
        "namespace": descriptor.namespace,
        "node_count": len(graph["nodes"]),
        "edge_count": len(graph["edges"]),
        "node_ids": sorted(graph["nodes"]),
        "edge_ids": sorted(graph["edges"]),
    }


def _space_root(artifact_root: str, descriptor: GraphSpaceDescriptor) -> Path:
    root = Path(artifact_root) / "workspaces" / descriptor.workspace / descriptor.namespace
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_graph(root: Path) -> dict[str, Any]:
    path = root / "graph.json"
    if not path.exists():
        return {"nodes": {}, "edges": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_graph(root: Path, graph: dict[str, Any]) -> None:
    (root / "graph.json").write_text(json.dumps(graph, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
