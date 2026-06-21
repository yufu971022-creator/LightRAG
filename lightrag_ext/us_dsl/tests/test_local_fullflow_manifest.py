from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.local_case_builder import build_local_cases
from lightrag_ext.us_dsl.local_fullflow_manifest import build_local_fullflow_manifest, manifest_counts
from lightrag_ext.us_dsl.local_us_inventory import discover_local_us_documents


def test_local_manifest_is_generated_without_user_input(tmp_path: Path) -> None:
    (tmp_path / "A_US.md").write_text("# US-1\nEvidence", encoding="utf-8")
    docs, _ = discover_local_us_documents(tmp_path)
    manifest = build_local_fullflow_manifest(docs, build_local_cases(docs))
    assert manifest.evaluation_mode == "local_fullflow"
    assert manifest.suite_id == "existing_us_local_fullflow_v1"
    assert manifest_counts(manifest)["accepted_document_count"] == 1
