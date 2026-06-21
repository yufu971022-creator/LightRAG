from __future__ import annotations

from lightrag_ext.us_dsl.skill_capability_probe import probe_skill_capabilities
from lightrag_ext.us_dsl.skill_contracts import build_skill_contracts


def test_skill_capability_is_probed_not_assumed() -> None:
    matrix = probe_skill_capabilities(build_skill_contracts())
    assert all(item.probed for item in matrix.values())
    assert all(item.evidence_source != "assumed" for item in matrix.values())
    assert matrix["CODE_CONTEXT_HANDOFF"].real_execution_performed is False
