from __future__ import annotations

from .local_fullflow_types import LocalDocumentRole


def classify_local_document_role(file_name: str) -> LocalDocumentRole:
    name = file_name.casefold()
    if any(marker in name for marker in ("高亮", "highlight", "质检", "quality")):
        return "QUALITY_ANNOTATION"
    if "synthetic" in name or "modification" in name or "change" in name:
        return "SYNTHETIC_CHANGE_SET"
    if "dfx" in name:
        return "DFX_VARIANT"
    if any(marker in name for marker in ("us", "userstory", "用户故事", "需求", "设计", "方案")):
        return "CANONICAL_SOURCE"
    return "UNKNOWN_SOURCE"


def role_is_canonical_fact_source(role: LocalDocumentRole) -> bool:
    return role in {"CANONICAL_SOURCE", "SYNTHETIC_CHANGE_SET", "DFX_VARIANT"}
