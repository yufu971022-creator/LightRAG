from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .multi_module_eval_types import ModuleManifestEntry, MultiModuleManifest, MultiModulePolicy

PLACEHOLDER_MANIFEST = "<<MODULE_MANIFEST_PATH>>"


class ManifestInputBlocked(ValueError):
    pass


def load_multi_module_manifest(path: str | Path) -> MultiModuleManifest:
    path_str = str(path)
    if not path_str or path_str == PLACEHOLDER_MANIFEST or "<<" in path_str:
        raise ManifestInputBlocked("BLOCKED_INPUT_SET: real multi-module manifest path is required")
    manifest_path = Path(path_str)
    if not manifest_path.exists():
        raise ManifestInputBlocked(f"BLOCKED_INPUT_SET: manifest not found: {manifest_path}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return parse_multi_module_manifest(raw, base_dir=manifest_path.parent)


def parse_multi_module_manifest(raw: dict[str, Any], *, base_dir: str | Path | None = None) -> MultiModuleManifest:
    policy = MultiModulePolicy(**raw.get("policy", {}))
    base = Path(base_dir) if base_dir is not None else None
    modules = [_parse_module(item, base_dir=base) for item in raw.get("modules", [])]
    manifest = MultiModuleManifest(
        suite_id=str(raw.get("suite_id", "")),
        output_dir=str(raw.get("output_dir", "artifacts/block_26b_multi_module_ab")),
        policy=policy,
        modules=modules,
    )
    validate_manifest_diversity(manifest)
    return manifest


def validate_manifest_diversity(manifest: MultiModuleManifest) -> dict[str, Any]:
    module_codes = [module.module_code for module in manifest.modules]
    duplicate_codes = sorted({code for code in module_codes if module_codes.count(code) > 1})
    holdout_count = sum(1 for module in manifest.modules if module.split == "HOLDOUT")
    domain_count = len({domain for module in manifest.modules for domain in module.domains})
    failures: list[str] = []
    if duplicate_codes:
        failures.append("DUPLICATE_MODULE_CODE")
    if len(manifest.modules) < manifest.policy.minimum_real_module_count:
        failures.append("BLOCKED_INSUFFICIENT_MODULE_DIVERSITY")
    if holdout_count < manifest.policy.minimum_holdout_module_count:
        failures.append("BLOCKED_MISSING_HOLDOUT_MODULE")
    if domain_count < manifest.policy.minimum_domain_coverage:
        failures.append("BLOCKED_INSUFFICIENT_DOMAIN_COVERAGE")
    return {
        "module_count": len(manifest.modules),
        "holdout_module_count": holdout_count,
        "domain_coverage_count": domain_count,
        "duplicate_module_codes": duplicate_codes,
        "passed": not failures,
        "failures": failures,
    }


def _parse_module(raw: dict[str, Any], *, base_dir: Path | None) -> ModuleManifestEntry:
    domains = list(raw.get("domains", []))
    domain_config = raw.get("domain_config")
    if domain_config:
        domain_path = _resolve_path(domain_config, base_dir)
        if domain_path.exists():
            payload = json.loads(domain_path.read_text(encoding="utf-8"))
            domains.extend(payload.get("domains", []))
    return ModuleManifestEntry(
        module_code=str(raw.get("module_code", "")),
        module_name=str(raw.get("module_name", "")),
        split=raw.get("split", "CALIBRATION"),
        source_files=[str(_resolve_path(item, base_dir)) for item in raw.get("source_files", [])],
        cases_file=str(_resolve_path(raw.get("cases_file", ""), base_dir)),
        domains=sorted({str(domain) for domain in domains}),
        term_registry=raw.get("term_registry"),
        domain_config=domain_config,
        version_config=raw.get("version_config"),
    )


def _resolve_path(value: str, base_dir: Path | None) -> Path:
    path = Path(str(value))
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path
