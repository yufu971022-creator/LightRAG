from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .document_lifecycle_types import LifecycleStorageCapabilities, to_plain_dict
from .lifecycle_storage_adapter import LocalLifecycleStorageAdapter


@dataclass
class LifecycleStorageCapabilityProbe:
    adapter: LocalLifecycleStorageAdapter = field(default_factory=LocalLifecycleStorageAdapter)
    run_count: int = 0

    def run(self) -> LifecycleStorageCapabilities:
        if self.run_count:
            return self._cached
        self.run_count += 1
        unsupported: list[str] = []
        evidence: dict[str, Any] = {"probe_run_count": self.run_count, "api_methods": []}
        try:
            self.adapter.upsert_raw_chunk({"chunk_id": "probe-c1", "stable_id": "probe-c1", "content": "probe", "content_hash": "h1"})
            evidence["api_methods"].append("upsert_raw_chunk")
            self.adapter.delete_raw_chunk("probe-c1")
            evidence["api_methods"].append("delete_raw_chunk")
        except Exception as exc:
            unsupported.extend(["KV upsert", "KV delete by ID"])
            evidence["kv_error"] = str(exc)
        try:
            chunk = {"chunk_id": "probe-c2", "stable_id": "probe-c2", "content": "probe vector", "content_hash": "h2"}
            self.adapter.upsert_chunk_vector(chunk)
            evidence["api_methods"].append("upsert_chunk_vector")
            self.adapter.delete_chunk_vector("probe-c2")
            evidence["api_methods"].append("delete_chunk_vector")
        except Exception as exc:
            unsupported.extend(["Vector upsert", "Vector delete by ID"])
            evidence["vector_error"] = str(exc)
        try:
            node_a = {"semantic_object_id": "probe-a", "canonical_name": "Probe A", "object_type": "FieldSpec"}
            node_b = {"semantic_object_id": "probe-b", "canonical_name": "Probe B", "object_type": "FieldSpec"}
            edge = {"semantic_relation_id": "probe-edge", "src_semantic_object_id": "probe-a", "tgt_semantic_object_id": "probe-b", "relation_type": "HasField"}
            self.adapter.upsert_pfss_node(node_a)
            self.adapter.upsert_pfss_node(node_b)
            evidence["api_methods"].append("upsert_pfss_node")
            self.adapter.upsert_pfss_edge(edge)
            evidence["api_methods"].append("upsert_pfss_edge")
            readback_ok = "probe-a" in self.adapter.pfss_nodes and "probe-edge" in self.adapter.pfss_edges
            self.adapter.delete_pfss_edge("probe-edge")
            evidence["api_methods"].append("delete_pfss_edge")
            self.adapter.delete_pfss_node("probe-a")
            self.adapter.delete_pfss_node("probe-b")
            evidence["api_methods"].append("delete_pfss_node")
        except Exception as exc:
            readback_ok = False
            unsupported.extend(["Graph upsert node", "Graph upsert edge", "Graph delete edge", "Graph delete node", "Graph get node", "Graph get edge"])
            evidence["graph_error"] = str(exc)
        unsupported = sorted(set(unsupported))
        blocked = bool(unsupported)
        self._cached = LifecycleStorageCapabilities(
            kv_upsert="KV upsert" not in unsupported,
            kv_delete="KV delete by ID" not in unsupported,
            vector_upsert="Vector upsert" not in unsupported,
            vector_delete="Vector delete by ID" not in unsupported,
            graph_node_upsert="Graph upsert node" not in unsupported,
            graph_edge_upsert="Graph upsert edge" not in unsupported,
            graph_edge_delete="Graph delete edge" not in unsupported,
            graph_node_delete="Graph delete node" not in unsupported,
            graph_readback=readback_ok,
            supports_safe_document_delete=not blocked,
            unsupported_operations=unsupported,
            evidence=evidence,
            blocked_by_core_gap=blocked,
            direct_storage_file_edit_used=self.adapter.direct_file_edit_used,
        )
        return self._cached


def probe_lifecycle_storage_capability(adapter: LocalLifecycleStorageAdapter | None = None) -> LifecycleStorageCapabilities:
    return LifecycleStorageCapabilityProbe(adapter or LocalLifecycleStorageAdapter()).run()


def capability_report(capabilities: LifecycleStorageCapabilities) -> dict[str, Any]:
    return to_plain_dict(capabilities)
