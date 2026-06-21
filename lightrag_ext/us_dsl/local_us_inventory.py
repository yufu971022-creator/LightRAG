from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .local_document_role_classifier import classify_local_document_role, role_is_canonical_fact_source
from .local_fullflow_types import LocalDiscoveredDocument, LocalDiscoveryPolicy

_US_BOUNDARY_RE = re.compile(
    r"(^|\n)\s*(#{1,6}\s*)?(US[-_ ][A-Z0-9]+[-_ ]\d+|US[-_ ]?\d+|User\s*Story|用户故事|需求|场景|Feature)",
    re.IGNORECASE,
)


def discover_local_us_documents(
    repo_root: str | Path,
    *,
    env_root: str | None = None,
    policy: LocalDiscoveryPolicy | None = None,
) -> tuple[list[LocalDiscoveredDocument], dict[str, object]]:
    policy = policy or LocalDiscoveryPolicy()
    root = Path(repo_root).resolve()
    discovery_roots = _discovery_roots(root, env_root=env_root)
    candidates = _discover_candidates(discovery_roots, policy=policy)
    expected_found = {name: False for name in policy.expected_files}
    documents: list[LocalDiscoveredDocument] = []
    seen_hashes: dict[str, str] = {}
    for index, path in enumerate(candidates):
        if path.name in expected_found:
            expected_found[path.name] = True
        digest = _sha256(path)
        role = classify_local_document_role(path.name)
        text, parse_status = _extract_text(path)
        duplicate_of = seen_hashes.get(digest)
        accepted = bool(text.strip()) and path.suffix.casefold() in policy.supported_extensions and duplicate_of is None
        rejection_reason = None
        if duplicate_of is not None:
            accepted = False
            rejection_reason = "duplicate_exact"
        elif path.suffix.casefold() not in policy.supported_extensions:
            accepted = False
            rejection_reason = "unsupported_format"
        elif not text.strip():
            accepted = False
            rejection_reason = "empty_content" if parse_status == "PARSED" else "parse_failed"
        elif role == "QUALITY_ANNOTATION":
            accepted = True
            rejection_reason = None
        if duplicate_of is None:
            seen_hashes[digest] = f"local-doc-{index:04d}"
        documents.append(
            LocalDiscoveredDocument(
                document_id=f"local-doc-{index:04d}",
                path=str(path),
                file_name=path.name,
                extension=path.suffix.casefold(),
                sha256=digest,
                size_bytes=path.stat().st_size,
                role=role,
                accepted=accepted,
                rejection_reason=rejection_reason,
                parse_status=parse_status,
                text_excerpt=_excerpt(text),
                detected_us_count=_detected_us_count(text),
                duplicate_of=duplicate_of,
            )
        )
    missing_expected = [name for name, found in expected_found.items() if not found]
    report = {
        "discovery_roots": [str(path) for path in discovery_roots],
        "discovery_executed_once": True,
        "expected_files": list(policy.expected_files),
        "missing_expected_files": missing_expected,
        "missing_expected_file_count": len(missing_expected),
    }
    return documents, report


def inventory_counts(documents: list[LocalDiscoveredDocument]) -> dict[str, int]:
    accepted = [doc for doc in documents if doc.accepted]
    return {
        "discovered_file_count": len(documents),
        "accepted_file_count": len(accepted),
        "rejected_file_count": len(documents) - len(accepted),
        "total_detected_us_count": sum(doc.detected_us_count for doc in documents),
        "unique_source_us_count": sum(doc.detected_us_count for doc in accepted),
        "duplicate_us_count": sum(doc.detected_us_count for doc in documents if doc.duplicate_of),
        "canonical_source_us_count": sum(doc.detected_us_count for doc in accepted if doc.role == "CANONICAL_SOURCE"),
        "synthetic_change_us_count": sum(doc.detected_us_count for doc in accepted if doc.role == "SYNTHETIC_CHANGE_SET"),
        "dfx_variant_us_count": sum(doc.detected_us_count for doc in accepted if doc.role == "DFX_VARIANT"),
        "quality_annotation_us_count": sum(doc.detected_us_count for doc in accepted if doc.role == "QUALITY_ANNOTATION"),
    }


def canonical_fact_documents(documents: list[LocalDiscoveredDocument]) -> list[LocalDiscoveredDocument]:
    return [doc for doc in documents if doc.accepted and role_is_canonical_fact_source(doc.role)]


def _discovery_roots(repo_root: Path, *, env_root: str | None) -> list[Path]:
    candidates: list[Path] = []
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())
    candidates.extend(
        [
            repo_root,
            repo_root / "data",
            repo_root / "datasets",
            repo_root / "artifacts",
            repo_root / "tests" / "fixtures",
        ]
    )
    candidates.extend(_declared_local_fixture_paths(repo_root))
    seen: set[Path] = set()
    roots: list[Path] = []
    for candidate in candidates:
        if candidate.exists() and candidate not in seen:
            seen.add(candidate)
            roots.append(candidate)
    return roots


def _declared_local_fixture_paths(repo_root: Path) -> list[Path]:
    # Local evaluation only: reuse the LC 66US runner's declared input locations
    # without broadening discovery to the whole user directory.
    return [
        repo_root / "lightrag_ext" / "us_dsl" / "tests" / "fixtures" / "LC_Acceptable_Bank_US_v1.md",
        repo_root.parent / "LC_Acceptable_Bank_US_v1.md",
    ]


def _discover_candidates(roots: list[Path], *, policy: LocalDiscoveryPolicy) -> list[Path]:
    results: dict[str, Path] = {}
    for root in roots:
        if root.is_file():
            iterable = [root]
        else:
            iterable = [path for path in root.rglob("*") if path.is_file()]
        for path in iterable:
            suffix = path.suffix.casefold()
            if suffix not in policy.supported_extensions:
                continue
            if not _name_matches_candidate_patterns(path.name):
                continue
            if any(part in {".git", "__pycache__", ".venv", "node_modules", ".uv-cache"} for part in path.parts):
                continue
            if _is_infrastructure_artifact(path):
                continue
            results[str(path.resolve())] = path.resolve()
    return sorted(results.values(), key=lambda item: str(item))


def _name_matches_candidate_patterns(file_name: str) -> bool:
    lower = file_name.casefold()
    if "US" in file_name or "UserStory" in file_name:
        return True
    return any(pattern in lower for pattern in ("用户故事", "需求", "设计", "方案", "dfx"))


def _is_infrastructure_artifact(path: Path) -> bool:
    name = path.name.casefold()
    if path.name.startswith("Block_") or "codex提示词" in name:
        return True
    infrastructure_names = (
        "git_status",
        "core_diff",
        "command_log",
        "safety_check",
        "cleanup",
        "report",
        "pycache",
    )
    return any(marker in name for marker in infrastructure_names)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_text(path: Path) -> tuple[str, str]:
    suffix = path.suffix.casefold()
    try:
        if suffix in {".md", ".txt", ".json", ".yaml", ".yml"}:
            return path.read_text(encoding="utf-8", errors="ignore"), "PARSED"
        if suffix == ".docx":
            return _extract_docx_text(path), "PARSED"
    except Exception:
        return "", "PARSE_FAILED"
    return "", "UNSUPPORTED"


def _extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    return "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))


def _detected_us_count(text: str) -> int:
    count = len(_US_BOUNDARY_RE.findall(text))
    if count:
        return count
    stripped = text.strip()
    return 1 if len(stripped) >= 20 else 0


def _excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed[:240]
