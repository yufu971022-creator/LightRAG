from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run_smoke(tmp_path: Path) -> dict:
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
    return json.loads((out / "term_normalization_report.json").read_text(encoding="utf-8"))


def test_isolated_pfss_smoke_creates_one_node_per_canonical_identity(tmp_path):
    report = _run_smoke(tmp_path)
    assert report["pfss_smoke"]["canonical_node_count"] == 3
    assert report["pfss_smoke"]["duplicate_semantic_object_count"] == 0


def test_approval_status_is_not_merged_into_bank_status(tmp_path):
    report = _run_smoke(tmp_path)
    assert report["pfss_smoke"]["approval_status_kept_separate"] is True
    assert report["pfss_smoke"]["total_node_count_after_approval_status"] == 4


def test_original_evidence_terms_are_traceable(tmp_path):
    report = _run_smoke(tmp_path)
    evidence_terms = {row["original_term"] for row in report["pfss_smoke"]["evidence"]}
    assert {"Current Handler", "当前处理人", "SWIFT CODE", "SWIFTCODE", "Bank Status", "银行状态"}.issubset(evidence_terms)


def test_sidecar_alias_records_are_idempotent(tmp_path):
    report = _run_smoke(tmp_path)
    assert report["pfss_smoke"]["idempotency_passed"] is True
