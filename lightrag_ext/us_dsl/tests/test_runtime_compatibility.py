from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.runtime_compatibility import generate_compatibility_matrix
from lightrag_ext.us_dsl.tests.engineering_closure_test_helpers import runtime_config


def test_compatibility_matrix_is_generated() -> None:
    matrix = generate_compatibility_matrix(runtime_config(), repo_root=Path.cwd())
    assert matrix["python_version"]
    assert matrix["extension_schema_version"] == "runtime-closure.v1"
    assert "LOCAL_JSON" in matrix["supported_local_storage_backends"]
