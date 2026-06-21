from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"Authorization\s*:\s*(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{12,}\b"),
]
_ABSOLUTE_USER_PATH = re.compile(r"(?:/Users/[^/\s]+|/home/[^/\s]+)")
_INTERNAL_ENDPOINT = re.compile(r"https?://[^\s\"']*(?:corp|internal|company|gateway)[^\s\"']*", re.IGNORECASE)
_INDEX_EXTENSIONS = {".graphml", ".vdb", ".db", ".sqlite", ".sqlite3", ".npy", ".npz", ".pkl", ".parquet"}
_RUNTIME_HARDCODE_PATTERNS = {
    "runtime_module_branch_count": re.compile(r"if\s+.*module_(?:code|name).*==", re.IGNORECASE),
    "entity_name_specific_rule_count": re.compile(r"if\s+.*(?:entity_name|object_name).*==", re.IGNORECASE),
    "module_specific_weight_count": re.compile(r"module_(?:code|name).*weight", re.IGNORECASE),
    "module_specific_skill_count": re.compile(r"(?:LC|FX|PAYMENT|BANK)_.*SKILL", re.IGNORECASE),
    "fixture_runtime_coupling_count": re.compile(r"sanitized_fixtures.*runtime", re.IGNORECASE),
    "local_filename_controls_runtime_logic_count": re.compile(r"if\s+.*(?:file_?name|filename).*==", re.IGNORECASE),
    "internal_endpoint_hardcode_count": _INTERNAL_ENDPOINT,
    "user_absolute_path_hardcode_count": _ABSOLUTE_USER_PATH,
}


@dataclass(frozen=True)
class SecurityScanReport:
    secret_hit_count: int = 0
    real_business_document_count: int = 0
    local_index_file_count: int = 0
    user_absolute_path_hit_count: int = 0
    internal_endpoint_hit_count: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)
    scanned_file_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "secret_hit_count": self.secret_hit_count,
            "real_business_document_count": self.real_business_document_count,
            "local_index_file_count": self.local_index_file_count,
            "user_absolute_path_hit_count": self.user_absolute_path_hit_count,
            "internal_endpoint_hit_count": self.internal_endpoint_hit_count,
            "findings": list(self.findings),
            "scanned_file_count": self.scanned_file_count,
        }


def scan_security(path: str | Path) -> SecurityScanReport:
    root = Path(path)
    counters = {
        "secret_hit_count": 0,
        "real_business_document_count": 0,
        "local_index_file_count": 0,
        "user_absolute_path_hit_count": 0,
        "internal_endpoint_hit_count": 0,
    }
    findings: list[dict[str, Any]] = []
    scanned = 0
    for item in _iter_files(root):
        rel = item.relative_to(root).as_posix() if item != root else item.name
        if item.name == ".env" or item.suffix.lower() in {".key", ".pem"}:
            counters["secret_hit_count"] += 1
            findings.append({"file": rel, "kind": "secret_file"})
        if item.suffix.lower() in _INDEX_EXTENSIONS:
            counters["local_index_file_count"] += 1
            findings.append({"file": rel, "kind": "local_index_file"})
        text = _read_text(item)
        if text is None:
            continue
        scanned += 1
        secret_hits = sum(len(pattern.findall(text)) for pattern in _SECRET_PATTERNS)
        path_hits = len(_ABSOLUTE_USER_PATH.findall(text))
        endpoint_hits = len(_INTERNAL_ENDPOINT.findall(text))
        counters["secret_hit_count"] += secret_hits
        counters["user_absolute_path_hit_count"] += path_hits
        counters["internal_endpoint_hit_count"] += endpoint_hits
        if secret_hits:
            findings.append({"file": rel, "kind": "secret_pattern", "count": secret_hits})
        if path_hits:
            findings.append({"file": rel, "kind": "absolute_user_path", "count": path_hits})
        if endpoint_hits:
            findings.append({"file": rel, "kind": "internal_endpoint", "count": endpoint_hits})
    return SecurityScanReport(scanned_file_count=scanned, findings=findings, **counters)


def scan_final_anti_hardcode(root: str | Path, files: list[str] | None = None) -> dict[str, Any]:
    base = Path(root)
    selected = [Path(item) for item in files] if files else [item for item in _iter_files(base) if item.suffix == ".py"]
    counters = {key: 0 for key in _RUNTIME_HARDCODE_PATTERNS}
    findings: list[dict[str, Any]] = []
    for path in selected:
        full = path if path.is_absolute() else base / path
        text = _read_text(full)
        if text is None:
            continue
        rel = full.relative_to(base).as_posix() if full.is_relative_to(base) else full.name
        for key, pattern in _RUNTIME_HARDCODE_PATTERNS.items():
            matches = list(pattern.finditer(text))
            counters[key] += len(matches)
            for match in matches:
                findings.append({"file": rel, "line": text.count("\n", 0, match.start()) + 1, "kind": key})
    return {**counters, "findings": findings, "scanned_file_count": len(selected)}


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for item in sorted(root.rglob("*")):
        if item.is_file():
            yield item


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None
