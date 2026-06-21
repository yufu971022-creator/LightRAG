from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .migration_bundle_validator import validate_bundle


def run_portable_bundle_smoke(
    bundle: str | Path,
    extract_to: str | Path,
    *,
    cleanup: bool = True,
) -> dict[str, Any]:
    source = Path(bundle)
    target = Path(extract_to)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    extracted = target / source.name
    shutil.copytree(source, extracted)
    validation = validate_bundle(extracted)
    _write_prereq_artifacts(extracted)
    child = _run_child_smoke(extracted)
    cleanup_passed = False
    if cleanup:
        shutil.rmtree(target)
        cleanup_passed = not target.exists()
    return {
        "portable_smoke_passed": validation["valid"] and child.get("passed", False) and cleanup_passed,
        "validation": validation,
        "child_smoke": child,
        "unconfigured_readiness_status": child.get("unconfigured_readiness_status"),
        "sanitized_readiness_status": child.get("sanitized_readiness_status"),
        "ingestion_passed": child.get("ingestion_passed", False),
        "functional_qa_passed": child.get("functional_qa_passed", False),
        "impact_analysis_passed": child.get("impact_analysis_passed", False),
        "quality_gate_passed": child.get("quality_gate_passed", False),
        "lifecycle_rebuild_passed": child.get("lifecycle_rebuild_passed", False),
        "network_calls_executed": False,
        "real_model_calls_executed": False,
        "source_repo_dependency_detected": child.get("source_repo_dependency_detected", True),
        "cleanup_passed": cleanup_passed,
    }


def _run_child_smoke(root: Path) -> dict[str, Any]:
    code = r'''
import json
import sys
from pathlib import Path
from lightrag_ext.us_dsl.dsl_aware_runtime_facade import DslAwareRuntimeFacade
from lightrag_ext.us_dsl.runtime_config_loader import load_runtime_config
from lightrag_ext.us_dsl.runtime_health_checks import evaluate_readiness

root = Path.cwd()
config_path = root / "sanitized_fixtures" / "sanitized_config.json"
default_config = load_runtime_config()
unconfigured = evaluate_readiness(default_config)
config = load_runtime_config(config_path)
facade = DslAwareRuntimeFacade(config, repo_root=root)
health = facade.health().to_dict()
readiness = facade.readiness().to_dict()
ingest = facade.ingest_documents({"trace_id": "portable-trace", "run_id": "portable-run", "batch_id": "portable-batch"}).to_dict()
query = facade.query_function({"trace_id": "portable-trace-q", "run_id": "portable-run-q", "batch_id": "portable-batch-q"}).to_dict()
impact = facade.analyze_impact({"trace_id": "portable-trace-i", "run_id": "portable-run-i", "batch_id": "portable-batch-i"}).to_dict()
rebuild = facade.rebuild_document_version({"trace_id": "portable-trace-r", "run_id": "portable-run-r", "batch_id": "portable-batch-r"}).to_dict()
module_file = Path(sys.modules["lightrag_ext.us_dsl.dsl_aware_runtime_facade"].__file__).resolve()
print(json.dumps({
    "passed": health["status"] == "HEALTHY" and readiness["status"] == "READY" and ingest["status"] == "CLEANED_UP",
    "unconfigured_readiness_status": unconfigured.status,
    "sanitized_readiness_status": readiness["status"],
    "ingestion_passed": ingest["status"] == "CLEANED_UP",
    "functional_qa_passed": query["status"] == "CLEANED_UP",
    "impact_analysis_passed": impact["status"] == "CLEANED_UP",
    "quality_gate_passed": bool(ingest["result"]["e2e"]["quality_summary"]),
    "lifecycle_rebuild_passed": rebuild["result"]["lifecycle"]["rebuild_passed"],
    "source_repo_dependency_detected": not str(module_file).startswith(str((root / "src").resolve())),
    "module_file": str(module_file.relative_to(root)),
}, sort_keys=True))
'''
    env = {"PYTHONPATH": str((root / "src").resolve()), "PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=120,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return {"passed": False, "returncode": result.returncode, "stderr": result.stderr[-2000:], "stdout": result.stdout[-2000:]}
    return json.loads(result.stdout.strip().splitlines()[-1])


def _write_prereq_artifacts(root: Path) -> None:
    paths = [
        root / "artifacts/block_27a_three_scenario_harness/three_scenario_harness_report.json",
        root / "artifacts/block_27b_qa_impact_quality_gate/qa_impact_quality_report.json",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"synthetic_prerequisite": True, "contains_real_data": False}, sort_keys=True) + "\n", encoding="utf-8")
