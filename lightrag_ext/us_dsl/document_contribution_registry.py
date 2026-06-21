from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .document_lifecycle_types import LifecycleDocumentBundle


@dataclass(frozen=True)
class ProjectionDeleteDecision:
    target_kind: str
    target_id: str
    active_contribution_count_after_delete: int
    physical_projection_delete_allowed: bool
    keep_projection: bool


class DocumentContributionRegistry:
    def __init__(self, repository) -> None:
        self.repository = repository

    def register_bundle_contributions(self, bundle: LifecycleDocumentBundle, *, batch_id: str, active: bool = True) -> None:
        for chunk in bundle.raw_chunks:
            chunk_id = stable_chunk_id(chunk)
            self.repository.upsert_raw_chunk_contribution(
                {
                    "contribution_id": f"contrib:chunk:{bundle.document_version_id}:{chunk_id}",
                    "document_version_id": bundle.document_version_id,
                    "chunk_id": chunk_id,
                    "active_flag": active,
                    "projection_hash": projection_hash(chunk),
                    "created_by_batch_id": batch_id,
                }
            )
        for obj in bundle.semantic_objects:
            object_id = str(obj["semantic_object_id"])
            self.repository.upsert_semantic_object_contribution(
                {
                    "contribution_id": f"contrib:obj:{bundle.document_version_id}:{object_id}",
                    "document_version_id": bundle.document_version_id,
                    "semantic_object_id": object_id,
                    "active_flag": active,
                    "projection_hash": projection_hash(obj),
                    "created_by_batch_id": batch_id,
                }
            )
        for rel in bundle.semantic_relations:
            relation_id = str(rel["semantic_relation_id"])
            self.repository.upsert_semantic_relation_contribution(
                {
                    "contribution_id": f"contrib:rel:{bundle.document_version_id}:{relation_id}",
                    "document_version_id": bundle.document_version_id,
                    "semantic_relation_id": relation_id,
                    "active_flag": active,
                    "projection_hash": projection_hash(rel),
                    "created_by_batch_id": batch_id,
                }
            )

    def deactivate_version(self, document_version_id: str, *, batch_id: str) -> None:
        self.repository.deactivate_version_contributions(document_version_id, batch_id)

    def active_chunk_contribution_count(self, chunk_id: str) -> int:
        return self.repository.active_chunk_contribution_count(chunk_id)

    def active_object_contribution_count(self, semantic_object_id: str) -> int:
        return self.repository.active_object_contribution_count(semantic_object_id)

    def active_relation_contribution_count(self, semantic_relation_id: str) -> int:
        return self.repository.active_relation_contribution_count(semantic_relation_id)

    def delete_decisions_for_bundle(self, bundle: LifecycleDocumentBundle) -> list[ProjectionDeleteDecision]:
        decisions: list[ProjectionDeleteDecision] = []
        for rel in sorted(bundle.semantic_relations, key=lambda item: item["semantic_relation_id"]):
            relation_id = str(rel["semantic_relation_id"])
            count = self.active_relation_contribution_count(relation_id)
            decisions.append(_decision("semantic_relation", relation_id, count))
        for obj in sorted(bundle.semantic_objects, key=lambda item: item["semantic_object_id"]):
            object_id = str(obj["semantic_object_id"])
            count = self.active_object_contribution_count(object_id)
            decisions.append(_decision("semantic_object", object_id, count))
        for chunk in sorted(bundle.raw_chunks, key=stable_chunk_id):
            chunk_id = stable_chunk_id(chunk)
            count = self.active_chunk_contribution_count(chunk_id)
            decisions.append(_decision("raw_chunk", chunk_id, count))
        return decisions

    def contribution_snapshot(self) -> dict[str, Any]:
        return {
            "raw_chunk_contributions": self.repository.list_active_contributions("raw_chunk_contributions"),
            "semantic_object_contributions": self.repository.list_active_contributions("semantic_object_contributions"),
            "semantic_relation_contributions": self.repository.list_active_contributions("semantic_relation_contributions"),
        }


def stable_chunk_id(chunk: dict[str, Any]) -> str:
    return str(chunk.get("stable_id") or chunk.get("chunk_stable_id") or chunk["chunk_id"])


def projection_hash(item: dict[str, Any]) -> str:
    if item.get("projection_hash"):
        return str(item["projection_hash"])
    if item.get("content_hash"):
        return str(item["content_hash"])
    return hashlib.sha256(repr(sorted(item.items())).encode("utf-8")).hexdigest()


def _decision(target_kind: str, target_id: str, count: int) -> ProjectionDeleteDecision:
    return ProjectionDeleteDecision(
        target_kind=target_kind,
        target_id=target_id,
        active_contribution_count_after_delete=count,
        physical_projection_delete_allowed=count == 0,
        keep_projection=count > 0,
    )
