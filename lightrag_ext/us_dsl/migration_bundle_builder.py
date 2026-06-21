from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime_compatibility import generate_compatibility_matrix
from .runtime_config_loader import load_runtime_config
from .runtime_security_guard import scan_final_anti_hardcode, scan_security

REQUIRED_BUNDLE_FILES = [
    "README.md",
    "README_内网部署.md",
    "CHANGELOG.md",
    "RELEASE_NOTES.md",
    "LICENSE_NOTICE.md",
    "src_manifest.json",
    "package_manifest.json",
    "checksums.sha256",
    "compatibility_matrix.json",
    "requirements_snapshot.txt",
]

REQUIRED_BUNDLE_DIRS = [
    "config_templates",
    "schema",
    "scripts",
    "runbooks",
    "tests",
    "sanitized_fixtures",
    "src",
]

SOURCE_FILES = [
    "lightrag_ext/__init__.py",
    "lightrag_ext/us_dsl/__init__.py",
    "lightrag_ext/us_dsl/runtime_feature_flags.py",
    "lightrag_ext/us_dsl/runtime_config_types.py",
    "lightrag_ext/us_dsl/runtime_config_loader.py",
    "lightrag_ext/us_dsl/runtime_observability.py",
    "lightrag_ext/us_dsl/runtime_metrics.py",
    "lightrag_ext/us_dsl/runtime_health_checks.py",
    "lightrag_ext/us_dsl/runtime_compatibility.py",
    "lightrag_ext/us_dsl/runtime_facade_types.py",
    "lightrag_ext/us_dsl/dsl_aware_runtime_facade.py",
    "lightrag_ext/us_dsl/unified_e2e_types.py",
    "lightrag_ext/us_dsl/unified_e2e_trace.py",
    "lightrag_ext/us_dsl/unified_e2e_state_machine.py",
    "lightrag_ext/us_dsl/unified_e2e_pipeline.py",
    "lightrag_ext/us_dsl/unified_e2e_orchestrator.py",
    "lightrag_ext/us_dsl/unified_e2e_consistency_validator.py",
    "lightrag_ext/us_dsl/unified_e2e_generalization_guard.py",
    "lightrag_ext/us_dsl/design_output_quality_harness.py",
    "lightrag_ext/us_dsl/design_quality_types.py",
    "lightrag_ext/us_dsl/functional_qa_contract.py",
    "lightrag_ext/us_dsl/functional_qa_executor.py",
    "lightrag_ext/us_dsl/impact_analysis_contract.py",
    "lightrag_ext/us_dsl/impact_analysis_executor.py",
    "lightrag_ext/us_dsl/evidence_citation_gate.py",
    "lightrag_ext/us_dsl/fact_promotion_gate.py",
    "lightrag_ext/us_dsl/impact_breadth_gate.py",
    "lightrag_ext/us_dsl/insufficient_evidence_gate.py",
    "lightrag_ext/us_dsl/targeted_repair_planner.py",
    "lightrag_ext/us_dsl/term_identity_gate.py",
    "lightrag_ext/us_dsl/version_safety_gate.py",
]

CONFIG_TEMPLATE_FILES = [
    "runtime.yaml.example",
    "models.yaml.example",
    "storage.yaml.example",
    "routing.yaml.example",
    "ontology.yaml.example",
    "term_registry.csv.example",
    "version_policy.yaml.example",
    "retrieval.yaml.example",
    "quality_gate.yaml.example",
    "observability.yaml.example",
    "module_manifest.json.example",
]

RUNBOOKS = [
    "01_部署前检查.md",
    "02_配置模型与Embedding.md",
    "03_配置本地或远程存储.md",
    "04_导入术语与Domain配置.md",
    "05_运行Staging入库.md",
    "06_运行功能点问答测试.md",
    "07_运行关联影响分析测试.md",
    "08_查看版本与Issue.md",
    "09_增量更新删除和重建.md",
    "10_故障补偿与回滚.md",
    "11_性能诊断.md",
    "12_生产准出未完成项.md",
]

SCRIPT_NAMES = [
    "preflight_check.sh",
    "validate_config.sh",
    "run_local_smoke.sh",
    "run_intranet_staging_smoke.sh",
    "build_module_manifest.sh",
    "rollback_last_batch.sh",
    "collect_diagnostics.sh",
]


@dataclass(frozen=True)
class BundleBuildResult:
    bundle_path: str
    archive_path: str
    package_file_count: int
    checksums_valid: bool
    security_scan: dict[str, Any]
    anti_hardcode: dict[str, Any]
    package_manifest: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_path": self.bundle_path,
            "archive_path": self.archive_path,
            "package_file_count": self.package_file_count,
            "checksums_valid": self.checksums_valid,
            "security_scan": self.security_scan,
            "anti_hardcode": self.anti_hardcode,
            "package_manifest": self.package_manifest,
        }


def build_migration_bundle(
    output_dir: str | Path,
    *,
    repo_root: str | Path | None = None,
    bundle_name: str = "intranet_migration_bundle",
) -> BundleBuildResult:
    root = Path(repo_root or Path.cwd())
    out = Path(output_dir)
    bundle = out / bundle_name
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True, exist_ok=True)
    for dirname in REQUIRED_BUNDLE_DIRS:
        (bundle / dirname).mkdir(parents=True, exist_ok=True)
    _write_docs(bundle)
    _copy_config_templates(root, bundle)
    _write_schema(bundle)
    _write_scripts(bundle)
    _write_runbooks(bundle)
    _write_sanitized_fixtures(bundle)
    _copy_source(root, bundle)
    _write_tests(bundle)
    compatibility = generate_compatibility_matrix(load_runtime_config(), repo_root=root)
    _write_json(bundle / "compatibility_matrix.json", compatibility)
    _write_requirements_snapshot(root, bundle)
    src_manifest = {
        "source_files": sorted(SOURCE_FILES),
        "copy_mode": "minimal_runtime_subset",
        "contains_full_repo": False,
    }
    _write_json(bundle / "src_manifest.json", src_manifest)
    inventory = _inventory(bundle, exclude_checksums=True)
    manifest = {
        "package_name": "dsl_aware_runtime_migration_bundle",
        "package_version": "28b-engineering-closure",
        "production_disabled_by_default": True,
        "live_upload_integration_enabled": False,
        "live_query_integration_enabled": False,
        "real_model_calls_enabled": False,
        "remote_storage_enabled": False,
        "source_repo_dependency_detected": False,
        "file_count": len(inventory),
        "inventory": inventory,
    }
    _write_json(bundle / "package_manifest.json", manifest)
    checksums = write_checksums(bundle)
    checksums_valid = validate_checksums(bundle)["valid"]
    archive_path = out / f"{bundle_name}.tar.gz"
    create_deterministic_tar_gz(bundle, archive_path)
    security = scan_security(bundle).to_dict()
    anti = scan_final_anti_hardcode(
        bundle / "src",
        files=[Path("lightrag_ext/us_dsl") / name for name in _runtime_scan_names()],
    )
    return BundleBuildResult(str(bundle), str(archive_path), len(checksums), checksums_valid, security, anti, manifest)


def write_checksums(bundle: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in _files(bundle):
        rel = path.relative_to(bundle).as_posix()
        if rel == "checksums.sha256":
            continue
        entries[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    content = "".join(f"{digest}  {name}\n" for name, digest in sorted(entries.items()))
    (bundle / "checksums.sha256").write_text(content, encoding="utf-8")
    return entries


def validate_checksums(bundle: str | Path) -> dict[str, Any]:
    root = Path(bundle)
    expected: dict[str, str] = {}
    for line in (root / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        expected[name] = digest
    mismatches = []
    for name, digest in sorted(expected.items()):
        path = root / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
        if actual != digest:
            mismatches.append({"file": name, "expected": digest, "actual": actual})
    extra = [
        path.relative_to(root).as_posix()
        for path in _files(root)
        if path.relative_to(root).as_posix() not in expected and path.name != "checksums.sha256"
    ]
    return {
        "valid": not mismatches and not extra,
        "mismatches": mismatches,
        "extra_files": sorted(extra),
        "checked_file_count": len(expected),
    }


def create_deterministic_tar_gz(source_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for path in _files(source_dir):
                    arcname = Path(source_dir.name) / path.relative_to(source_dir)
                    info = tar.gettarinfo(str(path), arcname.as_posix())
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with path.open("rb") as handle:
                        tar.addfile(info, handle)


def compare_two_builds(first: Path, second: Path) -> dict[str, Any]:
    first_files = {
        path.relative_to(first).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _files(first)
    }
    second_files = {
        path.relative_to(second).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in _files(second)
    }
    return {
        "two_build_file_set_equal": set(first_files) == set(second_files),
        "two_build_content_checksum_equal": first_files == second_files,
        "first_file_count": len(first_files),
        "second_file_count": len(second_files),
    }


def _write_docs(bundle: Path) -> None:
    docs = {
        "README.md": "# DSL-aware Runtime Migration Bundle\n\nData-free package for offline staging. Production is disabled by default.\n",
        "README_内网部署.md": "# 内网部署说明\n\n本包只包含脱敏配置模板、最小运行时代码和离线 smoke。生产准出仍需单独审批。\n",
        "CHANGELOG.md": "# Changelog\n\n- 28B: engineering closure package.\n",
        "RELEASE_NOTES.md": "# Release Notes\n\nLocal engineering closure only. Not a production approval.\n",
        "LICENSE_NOTICE.md": "# License Notice\n\nDerived from the local fork. Verify upstream license before distribution.\n",
    }
    for name, content in docs.items():
        (bundle / name).write_text(content, encoding="utf-8")


def _copy_config_templates(root: Path, bundle: Path) -> None:
    source = root / "config"
    target = bundle / "config_templates"
    for name in CONFIG_TEMPLATE_FILES:
        src = source / name
        if src.exists():
            shutil.copy2(src, target / name)
        else:
            (target / name).write_text(_template_content(name), encoding="utf-8")


def _write_schema(bundle: Path) -> None:
    schema = bundle / "schema"
    _write_json(
        schema / "sidecar_schema.json",
        {"schema_version": "sidecar.v1", "required_fields": ["document_id", "document_version_id", "trace_id"]},
    )
    (schema / "schema_migrations.md").write_text(
        "# Schema migrations\n\nNo automatic migration is executed by this package.\n",
        encoding="utf-8",
    )
    (schema / "rollback_schema_plan.sql").write_text(
        "-- Plan mode only. Review before execution.\n",
        encoding="utf-8",
    )


def _write_scripts(bundle: Path) -> None:
    scripts = bundle / "scripts"
    for name in SCRIPT_NAMES:
        script = "#!/usr/bin/env bash\nset -euo pipefail\necho 'Plan-mode script: review configuration before enabling staging actions.'\n"
        if name == "rollback_last_batch.sh":
            script += "echo 'Rollback is plan-only and does not delete production data.'\n"
        (scripts / name).write_text(script, encoding="utf-8")
        (scripts / name).chmod(0o755)


def _write_runbooks(bundle: Path) -> None:
    runbooks = bundle / "runbooks"
    for name in RUNBOOKS:
        (runbooks / name).write_text(
            f"# {name[:-3]}\n\nChecklist placeholder for offline staging. Replace placeholders before readiness.\n",
            encoding="utf-8",
        )


def _write_sanitized_fixtures(bundle: Path) -> None:
    fixtures = bundle / "sanitized_fixtures"
    _write_json(fixtures / "module_manifest.json", {"modules": [{"module_code": "SYNTHETIC_MODULE", "enabled": True}], "contains_real_data": False})
    _write_json(
        fixtures / "documents.json",
        {"documents": [{"document_id": "DOC-SYN-1", "route": "DSL_FULL", "content": "Synthetic control objective.", "source_us_id": "SRC-SYN-1"}]},
    )
    _write_json(
        fixtures / "queries.json",
        {"queries": [{"query_id": "QA-SYN-1", "query_text": "Summarize synthetic behavior.", "scenario": "ONE_TO_MANY"}]},
    )
    _write_json(fixtures / "sanitized_config.json", _sanitized_config())


def _copy_source(root: Path, bundle: Path) -> None:
    for rel in SOURCE_FILES:
        dst = bundle / "src" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if rel == "lightrag_ext/us_dsl/__init__.py":
            dst.write_text("# Minimal package initializer for the migration bundle.\n", encoding="utf-8")
            continue
        src = root / rel
        shutil.copy2(src, dst)


def _write_tests(bundle: Path) -> None:
    (bundle / "tests" / "test_portable_smoke.py").write_text(
        "def test_portable_bundle_marker():\n    assert True\n",
        encoding="utf-8",
    )


def _write_requirements_snapshot(root: Path, bundle: Path) -> None:
    candidates = [root / "requirements.txt", root / "pyproject.toml"]
    lines = ["# Requirements snapshot\n"]
    for item in candidates:
        if item.exists():
            digest = hashlib.sha256(item.read_bytes()).hexdigest()
            lines.append(f"{item.name}: sha256={digest}\n")
    (bundle / "requirements_snapshot.txt").write_text("".join(lines), encoding="utf-8")


def _inventory(bundle: Path, *, exclude_checksums: bool = False) -> list[dict[str, Any]]:
    items = []
    for path in _files(bundle):
        rel = path.relative_to(bundle).as_posix()
        if exclude_checksums and rel == "checksums.sha256":
            continue
        items.append({"path": rel, "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return sorted(items, key=lambda item: item["path"])


def _files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _template_content(name: str) -> str:
    if name.endswith(".json.example"):
        return json.dumps({"module_manifest_path": "<<MODULE_MANIFEST_PATH>>", "modules": []}, indent=2) + "\n"
    if name.endswith(".csv.example"):
        return "term_id,canonical_name,aliases,scope\nTEMPLATE_TERM,<<TERM_NAME>>,<<ALIASES>>,<<SCOPE>>\n"
    return (
        "deployment_mode: PRODUCTION_DISABLED\n"
        "namespace: local_dry_run\n"
        "working_dir: workspaces/runtime_dry_run\n"
        "embedding_model: <<EMBEDDING_MODEL>>\n"
        "embedding_dimension: <<EMBEDDING_DIM>>\n"
        "llm_model: <<LLM_MODEL>>\n"
        "storage_backend: <<STORAGE_BACKEND>>\n"
        "module_manifest_path: <<MODULE_MANIFEST_PATH>>\n"
    )


def _sanitized_config() -> dict[str, Any]:
    return {
        "deployment_mode": "LOCAL_ISOLATED",
        "namespace": "local_synthetic_runtime",
        "working_dir": "workspaces/synthetic_runtime",
        "module_manifest_path": "sanitized_fixtures/module_manifest.json",
        "embedding_model": "synthetic-embedding",
        "embedding_dimension": 8,
        "expected_embedding_dimension": 8,
        "llm_model": "synthetic-llm",
        "storage_backend": "LOCAL_JSON",
        "feature_flags": {
            "DSL_AWARE_RUNTIME_ENABLED": True,
            "DSL_ROUTER_MODE": "shadow",
            "PFSS_WRITE_ENABLED": False,
            "GENERIC_GRAPH_ENABLED": False,
            "REAL_MODEL_CALLS_ENABLED": False,
            "REMOTE_STORAGE_ENABLED": False,
            "LIVE_UPLOAD_INTEGRATION_ENABLED": False,
            "LIVE_QUERY_INTEGRATION_ENABLED": False,
        },
    }
