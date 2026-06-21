from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

from .migration_bundle_builder import REQUIRED_BUNDLE_DIRS, REQUIRED_BUNDLE_FILES, validate_checksums
from .runtime_security_guard import scan_final_anti_hardcode, scan_security


def validate_bundle(bundle: str | Path, *, verify_checksums: bool = True, scan_hardcodes: bool = True) -> dict[str, Any]:
    root = _bundle_root(Path(bundle))
    missing_files = [name for name in REQUIRED_BUNDLE_FILES if not (root / name).exists()]
    missing_dirs = [name for name in REQUIRED_BUNDLE_DIRS if not (root / name).is_dir()]
    checksum_report = validate_checksums(root) if verify_checksums else {"valid": True, "checked_file_count": 0}
    security = scan_security(root).to_dict()
    anti = (
        scan_final_anti_hardcode(
            root / "src",
            files=[Path("lightrag_ext/us_dsl") / name for name in _runtime_scan_names()],
        )
        if scan_hardcodes
        else {}
    )
    source_repo_dependency_detected = _source_repo_dependency_detected(root)
    package_inventory = [path.relative_to(root).as_posix() for path in sorted(root.rglob("*")) if path.is_file()]
    return {
        "valid": not missing_files
        and not missing_dirs
        and checksum_report.get("valid", False)
        and _security_passed(security)
        and not source_repo_dependency_detected,
        "bundle_path": str(root),
        "missing_files": missing_files,
        "missing_dirs": missing_dirs,
        "checksums": checksum_report,
        "security_scan": security,
        "anti_hardcode": anti,
        "source_repo_dependency_detected": source_repo_dependency_detected,
        "package_file_count": len(package_inventory),
        "package_inventory": package_inventory,
    }


def extract_archive(archive: str | Path, target: str | Path) -> Path:
    archive_path = Path(archive)
    target_path = Path(target)
    target_path.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(target_path)
    roots = [item for item in target_path.iterdir() if item.is_dir()]
    return roots[0] if len(roots) == 1 else target_path


def _bundle_root(path: Path) -> Path:
    if path.is_file() and path.suffixes[-2:] == [".tar", ".gz"]:
        raise ValueError("archive validation requires extraction before validate_bundle")
    return path


def _security_passed(report: dict[str, Any]) -> bool:
    return all(
        int(report.get(key, 0)) == 0
        for key in [
            "secret_hit_count",
            "real_business_document_count",
            "local_index_file_count",
            "user_absolute_path_hit_count",
            "internal_endpoint_hit_count",
        ]
    )


def _source_repo_dependency_detected(root: Path) -> bool:
    manifest = root / "package_manifest.json"
    if not manifest.exists():
        return True
    text = manifest.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return True
    return bool(data.get("source_repo_dependency_detected", False)) or "/Users/" in text or "/home/" in text


def _runtime_scan_names() -> list[str]:
    return [
        "runtime_feature_flags.py",
        "runtime_config_types.py",
        "runtime_config_loader.py",
        "runtime_observability.py",
        "runtime_metrics.py",
        "runtime_health_checks.py",
        "runtime_compatibility.py",
        "runtime_facade_types.py",
        "dsl_aware_runtime_facade.py",
    ]
