from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeterministicFakeEmbedding:
    dim: int = 8
    input_count: int = 0
    reused_count: int = 0
    recomputed_count: int = 0

    def vectorize(self, target_id: str, text: str) -> list[float]:
        self.input_count += 1
        self.recomputed_count += 1
        digest = hashlib.sha256(f"{target_id}:{text}".encode("utf-8")).digest()
        return [round(byte / 255.0, 6) for byte in digest[: self.dim]]

    def mark_reused(self) -> None:
        self.reused_count += 1


@dataclass
class LocalLifecycleStorageAdapter:
    embedding: DeterministicFakeEmbedding = field(default_factory=DeterministicFakeEmbedding)
    raw_chunks: dict[str, dict[str, Any]] = field(default_factory=dict)
    chunk_vectors: dict[str, dict[str, Any]] = field(default_factory=dict)
    pfss_nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    pfss_edges: dict[str, dict[str, Any]] = field(default_factory=dict)
    entity_vectors: dict[str, dict[str, Any]] = field(default_factory=dict)
    relation_vectors: dict[str, dict[str, Any]] = field(default_factory=dict)
    operation_log: list[dict[str, Any]] = field(default_factory=list)
    direct_file_edit_used: bool = False
    network_called: bool = False
    real_model_called: bool = False

    def upsert_raw_chunk(self, chunk: dict[str, Any]) -> dict[str, Any] | None:
        target_id = _chunk_projection_id(chunk)
        preimage = copy.deepcopy(self.raw_chunks.get(target_id))
        self.raw_chunks[target_id] = copy.deepcopy({**chunk, "projection_id": target_id})
        self._log("upsert_raw_chunk", target_id)
        return preimage

    def delete_raw_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        preimage = copy.deepcopy(self.raw_chunks.pop(chunk_id, None))
        self._log("delete_raw_chunk", chunk_id)
        return preimage

    def upsert_chunk_vector(self, chunk: dict[str, Any]) -> dict[str, Any] | None:
        target_id = _chunk_projection_id(chunk)
        projection_hash = str(chunk.get("projection_hash") or chunk.get("content_hash") or _hash(chunk.get("content", "")))
        preimage = copy.deepcopy(self.chunk_vectors.get(target_id))
        if preimage and preimage.get("projection_hash") == projection_hash:
            self.embedding.mark_reused()
            self._log("reuse_chunk_vector", target_id)
            return preimage
        vector = self.embedding.vectorize(target_id, str(chunk.get("content", target_id)))
        self.chunk_vectors[target_id] = {"id": target_id, "projection_hash": projection_hash, "vector": vector}
        self._log("upsert_chunk_vector", target_id)
        return preimage

    def delete_chunk_vector(self, chunk_id: str) -> dict[str, Any] | None:
        preimage = copy.deepcopy(self.chunk_vectors.pop(chunk_id, None))
        self._log("delete_chunk_vector", chunk_id)
        return preimage

    def upsert_pfss_node(self, obj: dict[str, Any]) -> dict[str, Any] | None:
        node_id = str(obj["semantic_object_id"])
        preimage = copy.deepcopy(self.pfss_nodes.get(node_id))
        self.pfss_nodes[node_id] = copy.deepcopy(obj)
        self._log("upsert_pfss_node", node_id)
        return preimage

    def delete_pfss_node(self, node_id: str) -> dict[str, Any] | None:
        dangling_edges = [edge_id for edge_id, edge in self.pfss_edges.items() if edge.get("src_semantic_object_id") == node_id or edge.get("tgt_semantic_object_id") == node_id]
        if dangling_edges:
            raise ValueError(f"cannot_delete_node_with_edges:{node_id}")
        preimage = copy.deepcopy(self.pfss_nodes.pop(node_id, None))
        self._log("delete_pfss_node", node_id)
        return preimage

    def upsert_pfss_edge(self, rel: dict[str, Any]) -> dict[str, Any] | None:
        edge_id = str(rel["semantic_relation_id"])
        src = str(rel["src_semantic_object_id"])
        tgt = str(rel["tgt_semantic_object_id"])
        if src not in self.pfss_nodes or tgt not in self.pfss_nodes:
            raise ValueError(f"dangling_edge:{edge_id}")
        preimage = copy.deepcopy(self.pfss_edges.get(edge_id))
        self.pfss_edges[edge_id] = copy.deepcopy(rel)
        self._log("upsert_pfss_edge", edge_id)
        return preimage

    def delete_pfss_edge(self, edge_id: str) -> dict[str, Any] | None:
        preimage = copy.deepcopy(self.pfss_edges.pop(edge_id, None))
        self._log("delete_pfss_edge", edge_id)
        return preimage

    def upsert_entity_vector(self, obj: dict[str, Any]) -> dict[str, Any] | None:
        obj_id = str(obj["semantic_object_id"])
        projection_hash = str(obj.get("projection_hash") or _hash(_vector_payload(obj)))
        preimage = copy.deepcopy(self.entity_vectors.get(obj_id))
        if preimage and preimage.get("projection_hash") == projection_hash:
            self.embedding.mark_reused()
            self._log("reuse_entity_vector", obj_id)
            return preimage
        vector = self.embedding.vectorize(obj_id, str(obj.get("canonical_name", obj_id)))
        self.entity_vectors[obj_id] = {"id": obj_id, "projection_hash": projection_hash, "vector": vector}
        self._log("upsert_entity_vector", obj_id)
        return preimage

    def delete_entity_vector(self, obj_id: str) -> dict[str, Any] | None:
        preimage = copy.deepcopy(self.entity_vectors.pop(obj_id, None))
        self._log("delete_entity_vector", obj_id)
        return preimage

    def upsert_relation_vector(self, rel: dict[str, Any]) -> dict[str, Any] | None:
        rel_id = str(rel["semantic_relation_id"])
        projection_hash = str(rel.get("projection_hash") or _hash(_vector_payload(rel)))
        preimage = copy.deepcopy(self.relation_vectors.get(rel_id))
        if preimage and preimage.get("projection_hash") == projection_hash:
            self.embedding.mark_reused()
            self._log("reuse_relation_vector", rel_id)
            return preimage
        vector = self.embedding.vectorize(rel_id, str(rel.get("relation_type", rel_id)))
        self.relation_vectors[rel_id] = {"id": rel_id, "projection_hash": projection_hash, "vector": vector}
        self._log("upsert_relation_vector", rel_id)
        return preimage

    def delete_relation_vector(self, rel_id: str) -> dict[str, Any] | None:
        preimage = copy.deepcopy(self.relation_vectors.pop(rel_id, None))
        self._log("delete_relation_vector", rel_id)
        return preimage

    def restore(self, store_name: str, target_id: str, preimage: dict[str, Any] | None) -> None:
        store = getattr(self, store_name)
        if preimage is None:
            store.pop(target_id, None)
        else:
            store[target_id] = copy.deepcopy(preimage)
        self._log("restore", f"{store_name}:{target_id}")

    def snapshot(self) -> dict[str, Any]:
        return {
            "raw_chunks": copy.deepcopy(self.raw_chunks),
            "chunk_vectors": copy.deepcopy(self.chunk_vectors),
            "pfss_nodes": copy.deepcopy(self.pfss_nodes),
            "pfss_edges": copy.deepcopy(self.pfss_edges),
            "entity_vectors": copy.deepcopy(self.entity_vectors),
            "relation_vectors": copy.deepcopy(self.relation_vectors),
            "embedding": {
                "embedding_input_count": self.embedding.input_count,
                "embedding_reused_count": self.embedding.reused_count,
                "embedding_recomputed_count": self.embedding.recomputed_count,
            },
        }

    def restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.raw_chunks = copy.deepcopy(snapshot["raw_chunks"])
        self.chunk_vectors = copy.deepcopy(snapshot["chunk_vectors"])
        self.pfss_nodes = copy.deepcopy(snapshot["pfss_nodes"])
        self.pfss_edges = copy.deepcopy(snapshot["pfss_edges"])
        self.entity_vectors = copy.deepcopy(snapshot["entity_vectors"])
        self.relation_vectors = copy.deepcopy(snapshot["relation_vectors"])
        embedding = snapshot.get("embedding", {})
        self.embedding.input_count = int(embedding.get("embedding_input_count", self.embedding.input_count))
        self.embedding.reused_count = int(embedding.get("embedding_reused_count", self.embedding.reused_count))
        self.embedding.recomputed_count = int(embedding.get("embedding_recomputed_count", self.embedding.recomputed_count))
        self._log("restore_snapshot", "all")

    def counts(self) -> dict[str, int]:
        return {
            "raw_chunk_count": len(self.raw_chunks),
            "chunk_vector_count": len(self.chunk_vectors),
            "pfss_node_count": len(self.pfss_nodes),
            "pfss_edge_count": len(self.pfss_edges),
            "entity_vector_count": len(self.entity_vectors),
            "relation_vector_count": len(self.relation_vectors),
        }

    def dangling_edge_count(self) -> int:
        node_ids = set(self.pfss_nodes)
        return sum(1 for edge in self.pfss_edges.values() if edge.get("src_semantic_object_id") not in node_ids or edge.get("tgt_semantic_object_id") not in node_ids)

    def orphan_vector_count(self) -> int:
        return len(set(self.chunk_vectors) - set(self.raw_chunks)) + len(set(self.entity_vectors) - set(self.pfss_nodes)) + len(set(self.relation_vectors) - set(self.pfss_edges))

    def duplicate_projection_count(self) -> int:
        return 0

    def issue_object_written_to_pfss_count(self) -> int:
        issue_types = {"VERSION_REVIEW_REQUIRED", "MISSING_EVIDENCE", "INVALID_TYPE", "REVIEW_REQUIRED", "INFO_ONLY"}
        return sum(1 for node in self.pfss_nodes.values() if node.get("object_type") in issue_types)

    def _log(self, operation: str, target_id: str) -> None:
        self.operation_log.append({"operation": operation, "target_id": target_id})


def _chunk_projection_id(chunk: dict[str, Any]) -> str:
    return str(chunk.get("stable_id") or chunk.get("chunk_stable_id") or chunk["chunk_id"])


def _vector_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key not in {"created_at", "updated_at", "document_version_id"}}


def _hash(value: Any) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()
