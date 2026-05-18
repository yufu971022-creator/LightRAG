from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from lightrag.base import BaseVectorStorage
from lightrag.kg.json_kv_impl import JsonKVStorage
from lightrag.kg.shared_storage import initialize_share_data
from lightrag.utils import EmbeddingFunc


EMBEDDING_DIM = 8
CHUNKS_VDB_META_FIELDS = {
    "content",
    "full_doc_id",
    "file_path",
    "metadata",
    "source_text_unit_id",
    "source_us_id",
    "feature_key",
    "domain_code",
    "section_type",
    "text_hash",
    "source_span",
}


@dataclass
class FakeEmbeddingRecorder:
    embedding_dim: int = EMBEDDING_DIM
    call_count: int = 0
    embedded_text_count: int = 0
    inputs: list[str] = field(default_factory=list)

    def embedding_func(self) -> EmbeddingFunc:
        return EmbeddingFunc(
            embedding_dim=self.embedding_dim,
            func=self._embed,
            model_name="dsl-test-fake-embedding",
            supports_asymmetric=True,
        )

    async def _embed(self, texts: list[str], **_kwargs) -> np.ndarray:
        self.call_count += 1
        self.embedded_text_count += len(texts)
        self.inputs.extend(texts)
        return np.array([_hash_vector(text, self.embedding_dim) for text in texts])


@dataclass
class TestNamespaceVectorStorage(BaseVectorStorage):
    """Small on-disk test vector storage used only when NanoVectorDB is unavailable."""

    data: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_embedding_func()
        working_dir = Path(self.global_config["working_dir"])
        workspace_dir = working_dir / self.workspace if self.workspace else working_dir
        workspace_dir.mkdir(parents=True, exist_ok=True)
        self._file_name = workspace_dir / f"vdb_{self.namespace}.json"

    async def initialize(self):
        if self._file_name.exists():
            self.data = json.loads(self._file_name.read_text(encoding="utf-8"))

    async def upsert(self, data: dict[str, dict[str, Any]]) -> None:
        if not data:
            return
        texts = [value["content"] for value in data.values()]
        vectors = await self.embedding_func(texts, context="document")
        for (key, value), vector in zip(data.items(), vectors, strict=True):
            self.data[key] = {
                "__id__": key,
                **{field: value.get(field) for field in self.meta_fields},
                "vector": [float(item) for item in vector],
            }

    async def query(
        self,
        query: str,
        top_k: int,
        query_embedding: list[float] = None,
    ) -> list[dict[str, Any]]:
        _ = query, top_k, query_embedding
        return []

    async def delete_entity(self, entity_name: str) -> None:
        _ = entity_name

    async def delete_entity_relation(self, entity_name: str) -> None:
        _ = entity_name

    async def get_by_id(self, id: str) -> dict[str, Any] | None:
        value = self.data.get(id)
        return dict(value) if value else None

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any] | None]:
        return [await self.get_by_id(id) for id in ids]

    async def delete(self, ids: list[str]):
        for id in ids:
            self.data.pop(id, None)

    async def get_vectors_by_ids(self, ids: list[str]) -> dict[str, list[float]]:
        return {
            id: value["vector"]
            for id in ids
            if (value := self.data.get(id)) is not None
        }

    async def index_done_callback(self) -> bool:
        self._file_name.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True

    async def drop(self) -> dict[str, str]:
        self.data.clear()
        await self.index_done_callback()
        return {"status": "success", "message": "data dropped"}


def build_test_namespace_storages(
    *,
    working_dir: str | Path,
    workspace: str,
    text_chunks_namespace: str,
    chunks_vdb_namespace: str,
    embedding_recorder: FakeEmbeddingRecorder,
):
    initialize_share_data()
    global_config = {
        "working_dir": str(working_dir),
        "embedding_batch_num": 16,
        "vector_db_storage_cls_kwargs": {"cosine_better_than_threshold": 0.2},
    }
    embedding_func = embedding_recorder.embedding_func()
    text_chunks = JsonKVStorage(
        namespace=text_chunks_namespace,
        workspace=workspace,
        global_config=global_config,
        embedding_func=embedding_func,
    )
    vector_cls, vector_type, risk = _vector_storage_class()
    chunks_vdb = vector_cls(
        namespace=chunks_vdb_namespace,
        workspace=workspace,
        global_config=global_config,
        embedding_func=embedding_func,
        meta_fields=CHUNKS_VDB_META_FIELDS,
    )
    return text_chunks, chunks_vdb, "JsonKVStorage", vector_type, risk


def namespace_is_safe(*values: str | None) -> bool:
    return all(value and ("test" in value or "dsl_test" in value) for value in values)


def _vector_storage_class():
    try:
        from lightrag.kg.nano_vector_db_impl import NanoVectorDBStorage
    except Exception as exc:
        return (
            TestNamespaceVectorStorage,
            "TestNamespaceVectorStorage",
            f"NanoVectorDBStorage unavailable; using test vector storage fallback: {exc.__class__.__name__}: {exc}",
        )
    return NanoVectorDBStorage, "NanoVectorDBStorage", None


def _hash_vector(text: str, dim: int) -> list[float]:
    import hashlib

    digest = hashlib.md5(text.encode("utf-8")).digest()
    return [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(dim)]


__all__ = [
    "CHUNKS_VDB_META_FIELDS",
    "FakeEmbeddingRecorder",
    "TestNamespaceVectorStorage",
    "build_test_namespace_storages",
    "namespace_is_safe",
]
