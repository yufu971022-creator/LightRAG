from __future__ import annotations

from lightrag_ext.us_dsl.requirement_scenario_profile import build_requirement_scenario_profile
from lightrag_ext.us_dsl.tests.harness_27a_test_helpers import req_local, req_many, req_zero


def test_zero_to_one_profile_uses_novelty_and_coverage() -> None:
    profile = build_requirement_scenario_profile(req_zero())
    assert profile.novelty_score > 0.7
    assert profile.existing_feature_coverage < 0.35
    assert profile.new_business_object_ratio > 0.6


def test_one_to_many_profile_uses_impact_breadth() -> None:
    profile = build_requirement_scenario_profile(req_many())
    assert profile.affected_feature_count > 1
    assert profile.affected_domain_count > 1
    assert profile.direct_impact_count + profile.indirect_impact_count >= 3


def test_one_to_one_x_profile_uses_local_scope_and_asset_coverage() -> None:
    profile = build_requirement_scenario_profile(req_local())
    assert profile.local_change_score > 0.65
    assert profile.existing_code_asset_coverage > 0.65
    assert profile.affected_domain_count == 1
