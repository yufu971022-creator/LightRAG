from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def smoke_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_dir = tmp_path_factory.mktemp("entity_type_resolution_smoke")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lightrag_ext.us_dsl.scripts.run_entity_type_resolution_smoke",
            "--output-dir",
            str(output_dir),
            "--fixture-suite",
            "--fake-deterministic-embedding",
            "--isolated-pfss-smoke",
            "--cleanup",
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return output_dir


def _load(output_dir: Path, name: str) -> dict[str, object]:
    return json.loads((output_dir / name).read_text(encoding="utf-8"))


def test_type_resolution_issue_is_persisted(smoke_output: Path) -> None:
    issue_snapshot = _load(smoke_output, "issue_snapshot.json")
    assert issue_snapshot["issue_count"] >= 1
    assert issue_snapshot["by_type"]["GENERIC_NER_TYPE_BLOCKED"] == 1


def test_issue_object_is_not_confirmed(smoke_output: Path) -> None:
    issue_snapshot = _load(smoke_output, "issue_snapshot.json")
    pfss_snapshot = _load(smoke_output, "pfss_type_snapshot.json")
    assert issue_snapshot["confirmed_issue_count"] == 0
    assert pfss_snapshot["issue_object_written_to_pfss_count"] == 0


def test_endpoint_closure_after_type_resolution(smoke_output: Path) -> None:
    pfss_snapshot = _load(smoke_output, "pfss_type_snapshot.json")
    assert pfss_snapshot["endpoint_closure_passed"] is True


def test_no_forbidden_relation_after_type_resolution(smoke_output: Path) -> None:
    pfss_snapshot = _load(smoke_output, "pfss_type_snapshot.json")
    assert pfss_snapshot["forbidden_relation_count"] == 0
