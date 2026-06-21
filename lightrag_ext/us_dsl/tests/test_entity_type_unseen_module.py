from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lightrag_ext.us_dsl.contextual_entity_type_resolver import ContextualEntityTypeResolver
from lightrag_ext.us_dsl.entity_type_resolution_types import EntityTypeResolutionContext


def _ctx(name: str, section: str | None, *, relation_type: str | None = None, relation_role: str | None = None, domain: str | None = "MonitoringReport") -> EntityTypeResolutionContext:
    return EntityTypeResolutionContext(
        document_type="product_design",
        module_code="MOD-RANDOM",
        primary_domain=domain,
        feature_key="UnseenFeature" if domain else None,
        section_type=section,
        relation_type=relation_type,
        relation_role=relation_role,
        original_entity_name=name,
        original_entity_type="Misc",
        source_us_id="US-25A1-1",
        text_unit_id="tu-unseen" if section or relation_type else None,
        source_span={"start": 0, "end": len(name)},
        evidence_text=f"{name} appears in a structured product design section.",
    )


@pytest.fixture(scope="module")
def closure_output(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_dir = tmp_path_factory.mktemp("entity_type_generalization_closure")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lightrag_ext.us_dsl.scripts.run_entity_type_generalization_closure",
            "--output-dir",
            str(output_dir),
            "--cross-domain-fixtures",
            "--unseen-name-suite",
            "--anti-hardcode-check",
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


def test_unseen_names_never_use_business_name_special_cases(closure_output: Path) -> None:
    report = _load(closure_output, "anti_hardcode_report.json")
    assert report["passed"] is True


def test_unseen_structured_list_resolves_to_report_spec() -> None:
    decision = ContextualEntityTypeResolver().resolve(_ctx("Alpha 记录清单", "query_section"))
    assert decision.resolved_entity_type == "ReportSpec"


def test_unseen_field_resolves_from_relation_role() -> None:
    decision = ContextualEntityTypeResolver().resolve(_ctx("Beta 状态列", "result_grid", relation_type="HasReportColumn", relation_role="target"))
    assert decision.resolved_entity_type == "FieldSpec"
    assert "relation_signature" in decision.signals_used or "section_type" in decision.signals_used


def test_unseen_task_resolves_from_section_and_relation_role() -> None:
    decision = ContextualEntityTypeResolver().resolve(_ctx("Gamma 审核任务", "task_rule", domain="Workflow"))
    assert decision.resolved_entity_type == "TaskRule"


def test_unseen_unsafe_auto_accept_count_is_zero(closure_output: Path) -> None:
    report = _load(closure_output, "unseen_name_results.json")
    assert report["unseen_fixture_count"] >= 20
    assert report["unsafe_auto_accept_count"] == 0


def test_no_live_upload_or_query_change(closure_output: Path) -> None:
    safety = _load(closure_output, "safety_check.json")
    assert safety["live_upload_behavior_changed"] is False
    assert safety["live_query_behavior_changed"] is False


def test_no_real_embedding_or_llm_calls(closure_output: Path) -> None:
    safety = _load(closure_output, "safety_check.json")
    assert safety["real_embedding_calls_executed"] is False
    assert safety["real_llm_calls_executed"] is False


def test_no_production_graph_or_database_write(closure_output: Path) -> None:
    safety = _load(closure_output, "safety_check.json")
    assert safety["production_graph_rewrite_executed"] is False
    assert safety["production_database_connected"] is False
    assert safety["neo4j_connected"] is False


def test_report_is_serializable(closure_output: Path) -> None:
    report = _load(closure_output, "generalization_closure_report.json")
    json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert report["artifacts_complete"] is True


def test_no_lightrag_core_modified(closure_output: Path) -> None:
    safety = _load(closure_output, "safety_check.json")
    assert safety["lightrag_core_modified"] is False
    assert (closure_output / "core_diff_check.txt").read_text(encoding="utf-8") == "NO_CORE_DIFF\n"


def test_cleanup_removes_workspaces(closure_output: Path) -> None:
    cleanup = _load(closure_output, "cleanup_report.json")
    assert cleanup["cleanup_passed"] is True
    assert not (closure_output / "workspaces" / "generalization_closure").exists()
