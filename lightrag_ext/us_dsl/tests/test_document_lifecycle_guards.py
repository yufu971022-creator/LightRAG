from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lightrag_ext.us_dsl.document_lifecycle_service import DocumentLifecycleService, build_lifecycle_fixture_bundle
from lightrag_ext.us_dsl.sqlite_sidecar_repository import SQLiteSidecarRepository


def test_no_real_embedding_or_llm_calls():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()

    repo.apply_lifecycle_migration()
    service = DocumentLifecycleService(repository=repo)
    v1 = build_lifecycle_fixture_bundle("v1")
    service.register_initial_version(v1, batch_id="b1")
    assert service.adapter.real_model_called is False
    assert service.adapter.network_called is False


def test_no_production_storage_connection():
    repo = SQLiteSidecarRepository(":memory:")
    repo.initialize_schema()

    repo.apply_lifecycle_migration()
    assert repo.db_path == ":memory:"


def test_report_is_serializable():
    path = Path("artifacts/block_24c1_document_lifecycle/document_lifecycle_report.json")
    if not path.exists():
        subprocess.run([
            ".venv/bin/python",
            "-m",
            "lightrag_ext.us_dsl.scripts.run_document_lifecycle_smoke",
            "--output-dir",
            "artifacts/block_24c1_document_lifecycle",
            "--fixture-suite",
            "--fake-deterministic-embedding",
            "--failure-injection-suite",
            "--cleanup",
        ], check=True, timeout=300)
    data = json.loads(path.read_text(encoding="utf-8"))
    json.dumps(data, sort_keys=True)
    assert data["artifacts_complete"] is True


def test_no_lightrag_core_modified():
    result = subprocess.run([
        "git",
        "diff",
        "--name-only",
        "--",
        "lightrag/lightrag.py",
        "lightrag/operate.py",
        "lightrag/prompt.py",
        "lightrag/api",
    ], capture_output=True, text=True, timeout=60, check=False)
    assert result.stdout.strip() == ""


def test_cleanup_removes_all_workspaces(tmp_path):
    out = tmp_path / "block24c1"
    subprocess.run([
        ".venv/bin/python",
        "-m",
        "lightrag_ext.us_dsl.scripts.run_document_lifecycle_smoke",
        "--output-dir",
        str(out),
        "--fixture-suite",
        "--fake-deterministic-embedding",
        "--failure-injection-suite",
        "--cleanup",
    ], check=True, timeout=300)
    report = json.loads((out / "cleanup_report.json").read_text(encoding="utf-8"))
    workspaces = list((out / "workspaces").iterdir()) if (out / "workspaces").exists() else []
    assert report["cleanup_passed"] is True
    assert workspaces == []
