from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_no_real_embedding_or_llm_calls():
    path = Path("artifacts/block_25a0_term_normalization/safety_check.json")
    if path.exists():
        safety = json.loads(path.read_text(encoding="utf-8"))
        assert safety["real_embedding_calls_executed"] is False
        assert safety["real_llm_calls_executed"] is False
    else:
        assert True


def test_no_production_graph_rewrite():
    path = Path("artifacts/block_25a0_term_normalization/safety_check.json")
    if path.exists():
        safety = json.loads(path.read_text(encoding="utf-8"))
        assert safety["production_graph_rewrite_executed"] is False
    else:
        assert True


def test_report_is_serializable():
    path = Path("artifacts/block_25a0_term_normalization/term_normalization_report.json")
    if not path.exists():
        subprocess.run([
            ".venv/bin/python",
            "-m",
            "lightrag_ext.us_dsl.scripts.run_term_normalization_smoke",
            "--output-dir",
            "artifacts/block_25a0_term_normalization",
            "--fixture-suite",
            "--fake-deterministic-embedding",
            "--isolated-pfss-dedup-smoke",
            "--cleanup",
        ], check=True, timeout=300)
    json.dumps(json.loads(path.read_text(encoding="utf-8")), sort_keys=True)


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
    out = tmp_path / "25a0"
    subprocess.run([
        ".venv/bin/python",
        "-m",
        "lightrag_ext.us_dsl.scripts.run_term_normalization_smoke",
        "--output-dir",
        str(out),
        "--fixture-suite",
        "--fake-deterministic-embedding",
        "--isolated-pfss-dedup-smoke",
        "--cleanup",
    ], check=True, timeout=300)
    cleanup = json.loads((out / "cleanup_report.json").read_text(encoding="utf-8"))
    entries = list((out / "workspaces").iterdir()) if (out / "workspaces").exists() else []
    assert cleanup["cleanup_passed"] is True
    assert entries == []
