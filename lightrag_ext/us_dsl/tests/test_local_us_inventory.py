from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.local_fullflow_types import LocalDiscoveryPolicy
from lightrag_ext.us_dsl.local_us_inventory import discover_local_us_documents, inventory_counts


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_local_inventory_discovers_all_supported_us_files_once(tmp_path: Path) -> None:
    _write(tmp_path / "A_US.md", "# US-1\nEvidence text")
    _write(tmp_path / "B_需求.txt", "需求: Evidence text")
    docs, report = discover_local_us_documents(tmp_path)
    assert report["discovery_executed_once"] is True
    assert {doc.file_name for doc in docs} == {"A_US.md", "B_需求.txt"}


def test_inventory_reports_missing_expected_files_without_looping(tmp_path: Path) -> None:
    policy = LocalDiscoveryPolicy(expected_files=("Expected_US.md",))
    docs, report = discover_local_us_documents(tmp_path, policy=policy)
    assert docs == []
    assert report["missing_expected_files"] == ["Expected_US.md"]


def test_all_valid_us_are_counted(tmp_path: Path) -> None:
    _write(tmp_path / "A_US.md", "# US-1\nText")
    _write(tmp_path / "B_US.md", "# US-2\nText")
    docs, _ = discover_local_us_documents(tmp_path)
    counts = inventory_counts(docs)
    assert counts["accepted_file_count"] == 2
    assert counts["unique_source_us_count"] == 2


def test_exact_duplicate_files_are_not_double_ingested(tmp_path: Path) -> None:
    _write(tmp_path / "A_US.md", "# US-1\nSame")
    _write(tmp_path / "B_US.md", "# US-1\nSame")
    docs, _ = discover_local_us_documents(tmp_path)
    counts = inventory_counts(docs)
    assert counts["accepted_file_count"] == 1
    assert counts["duplicate_us_count"] >= 1
