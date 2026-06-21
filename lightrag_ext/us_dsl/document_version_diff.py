from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .document_lifecycle_types import DiffItem, DocumentVersionDiff, LifecycleDocumentBundle

_VOLATILE_FIELDS = {
    "created_at",
    "updated_at",
    "document_version_id",
    "previous_version_id",
    "batch_id",
    "trace_id",
}


def build_document_version_diff(
    old_bundle: LifecycleDocumentBundle | None,
    new_bundle: LifecycleDocumentBundle,
    *,
    ignore_formatting_whitespace: bool = True,
) -> DocumentVersionDiff:
    old_content_hash = old_bundle.document_version.get("content_hash") if old_bundle else None
    new_content_hash = new_bundle.document_version.get("content_hash")
    old_version_id = old_bundle.document_version_id if old_bundle else None
    return DocumentVersionDiff(
        old_document_version_id=old_version_id,
        new_document_version_id=new_bundle.document_version_id,
        document_id=new_bundle.document_id,
        content_changed=old_content_hash != new_content_hash,
        **_section_diff(
            old_bundle.raw_chunks if old_bundle else [],
            new_bundle.raw_chunks,
            stable_key="chunk",
            ignore_formatting_whitespace=ignore_formatting_whitespace,
            prefixes=("added_chunks", "unchanged_chunks", "updated_chunks", "removed_chunks"),
        ),
        **_section_diff(
            old_bundle.source_text_units if old_bundle else [],
            new_bundle.source_text_units,
            stable_key="text_unit",
            ignore_formatting_whitespace=ignore_formatting_whitespace,
            prefixes=("added_text_units", "unchanged_text_units", "updated_text_units", "removed_text_units"),
        ),
        **_section_diff(
            old_bundle.semantic_objects if old_bundle else [],
            new_bundle.semantic_objects,
            stable_key="semantic_object",
            ignore_formatting_whitespace=ignore_formatting_whitespace,
            prefixes=("added_semantic_objects", "unchanged_semantic_objects", "updated_semantic_objects", "removed_semantic_objects"),
        ),
        **_section_diff(
            old_bundle.semantic_relations if old_bundle else [],
            new_bundle.semantic_relations,
            stable_key="semantic_relation",
            ignore_formatting_whitespace=ignore_formatting_whitespace,
            prefixes=("added_semantic_relations", "unchanged_semantic_relations", "updated_semantic_relations", "removed_semantic_relations"),
        ),
        **_issue_diff(old_bundle.issues if old_bundle else [], new_bundle.issues),
    )


def _section_diff(
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    *,
    stable_key: str,
    ignore_formatting_whitespace: bool,
    prefixes: tuple[str, str, str, str],
) -> dict[str, list[DiffItem]]:
    added_key, unchanged_key, updated_key, removed_key = prefixes
    old_index = _index_by_stable_id(old_items, stable_key, ignore_formatting_whitespace)
    new_index = _index_by_stable_id(new_items, stable_key, ignore_formatting_whitespace)
    added: list[DiffItem] = []
    unchanged: list[DiffItem] = []
    updated: list[DiffItem] = []
    removed: list[DiffItem] = []
    for stable_id in sorted(set(old_index) | set(new_index)):
        old = old_index.get(stable_id)
        new = new_index.get(stable_id)
        if old is None and new is not None:
            added.append(DiffItem(stable_id=stable_id, new=new["item"], new_hash=new["hash"], reason="added"))
        elif old is not None and new is None:
            removed.append(DiffItem(stable_id=stable_id, old=old["item"], old_hash=old["hash"], reason="removed"))
        elif old is not None and new is not None and old["hash"] == new["hash"]:
            unchanged.append(DiffItem(stable_id=stable_id, old=old["item"], new=new["item"], old_hash=old["hash"], new_hash=new["hash"], reason="unchanged"))
        elif old is not None and new is not None:
            updated.append(DiffItem(stable_id=stable_id, old=old["item"], new=new["item"], old_hash=old["hash"], new_hash=new["hash"], reason="projection_hash_changed"))
    return {
        added_key: added,
        unchanged_key: unchanged,
        updated_key: updated,
        removed_key: removed,
    }


def _issue_diff(old_items: list[dict[str, Any]], new_items: list[dict[str, Any]]) -> dict[str, list[DiffItem]]:
    old_index = _index_by_stable_id(old_items, "issue", True)
    new_index = _index_by_stable_id(new_items, "issue", True)
    opened: list[DiffItem] = []
    unchanged: list[DiffItem] = []
    resolved: list[DiffItem] = []
    for stable_id in sorted(set(old_index) | set(new_index)):
        old = old_index.get(stable_id)
        new = new_index.get(stable_id)
        if old is None and new is not None:
            opened.append(DiffItem(stable_id=stable_id, new=new["item"], new_hash=new["hash"], reason="opened"))
        elif old is not None and new is None:
            resolved.append(DiffItem(stable_id=stable_id, old=old["item"], old_hash=old["hash"], reason="resolved"))
        elif old is not None and new is not None and old["hash"] == new["hash"]:
            unchanged.append(DiffItem(stable_id=stable_id, old=old["item"], new=new["item"], old_hash=old["hash"], new_hash=new["hash"], reason="unchanged"))
        elif old is not None and new is not None:
            opened.append(DiffItem(stable_id=stable_id, old=old["item"], new=new["item"], old_hash=old["hash"], new_hash=new["hash"], reason="changed_issue_reopened"))
    return {"opened_issues": opened, "unchanged_issues": unchanged, "resolved_issues": resolved}


def _index_by_stable_id(items: list[dict[str, Any]], stable_key: str, ignore_formatting_whitespace: bool) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in items:
        stable_id = _stable_id(item, stable_key)
        indexed[stable_id] = {
            "item": item,
            "hash": _semantic_hash(item, stable_key, ignore_formatting_whitespace),
        }
    return indexed


def _stable_id(item: dict[str, Any], stable_key: str) -> str:
    for key in ("stable_id", "projection_id", "semantic_object_id", "semantic_relation_id", "chunk_stable_id", "text_unit_stable_id", "issue_stable_id"):
        value = item.get(key)
        if value:
            return str(value)
    fallback_keys = {
        "chunk": "chunk_id",
        "text_unit": "text_unit_id",
        "semantic_object": "semantic_object_id",
        "semantic_relation": "semantic_relation_id",
        "issue": "issue_id",
    }
    return str(item[fallback_keys[stable_key]])


def _semantic_hash(item: dict[str, Any], stable_key: str, ignore_formatting_whitespace: bool) -> str:
    for key in ("projection_hash", "evidence_mapping_hash"):
        if item.get(key):
            return str(item[key])
    if stable_key in {"chunk", "text_unit"} and item.get("content") is not None:
        content = str(item["content"])
        if ignore_formatting_whitespace:
            content = _normalize_ws(content)
        return _hash({"content": content, "stable_id": _stable_id(item, stable_key)})
    if item.get("content_hash") and not ignore_formatting_whitespace:
        return str(item["content_hash"])
    return _hash(_canonical_payload(item, ignore_formatting_whitespace=ignore_formatting_whitespace))


def _canonical_payload(item: dict[str, Any], *, ignore_formatting_whitespace: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in sorted(item.items()):
        if key in _VOLATILE_FIELDS or key.endswith("_id") and key not in {"semantic_object_id", "semantic_relation_id", "src_semantic_object_id", "tgt_semantic_object_id"}:
            continue
        if isinstance(value, str) and ignore_formatting_whitespace:
            value = _normalize_ws(value)
        payload[key] = value
    return payload


def _normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
