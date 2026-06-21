from __future__ import annotations

from lightrag_ext.us_dsl.tests.version_retrieval_test_helpers import current_candidates, make_candidate, resolver


def test_unique_explicit_current_is_confirmed() -> None:
    result = resolver().resolve(current_candidates("vg:unique-current"))
    assert result.resolution_status == "CONFIRMED_CURRENT"
    assert result.current_candidate_id == "m:uc:v2"


def test_unique_explicit_latest_is_confirmed() -> None:
    result = resolver().resolve(current_candidates("vg:unique-latest"))
    assert result.resolution_status == "CONFIRMED_CURRENT"
    assert result.current_candidate_id == "m:ul:v2"


def test_multiple_current_is_conflict() -> None:
    result = resolver().resolve(current_candidates("vg:multi-current"))
    assert result.resolution_status == "MULTIPLE_CURRENT_CONFLICT"
    assert result.safe_for_deterministic_answer is False


def test_multiple_latest_is_conflict() -> None:
    result = resolver().resolve(current_candidates("vg:multi-latest"))
    assert result.resolution_status == "MULTIPLE_LATEST_CONFLICT"
    assert result.safe_for_deterministic_answer is False


def test_safe_supersedes_terminal_is_current() -> None:
    result = resolver().resolve(current_candidates("vg:supersedes"))
    assert result.resolution_status == "CONFIRMED_CURRENT"
    assert result.current_candidate_id == "m:ss:v2"


def test_supersedes_cycle_is_conflict() -> None:
    result = resolver().resolve([
        make_candidate("vg:cycle", "m:cy:v1", "v1", "UNKNOWN", False, supersedes="m:cy:v2", review="CONFIRMED_SUPERSEDES"),
        make_candidate("vg:cycle", "m:cy:v2", "v2", "UNKNOWN", False, supersedes="m:cy:v1", review="CONFIRMED_SUPERSEDES"),
    ])
    assert result.resolution_status == "SUPERSEDES_CHAIN_CONFLICT"
    assert any(issue.issue_type == "SUPERSEDES_CYCLE" for issue in result.issues)


def test_missing_supersedes_target_is_conflict() -> None:
    result = resolver().resolve([
        make_candidate("vg:missing-target", "m:mt:v2", "v2", "UNKNOWN", False, supersedes="m:mt:v1", review="CONFIRMED_SUPERSEDES"),
    ])
    assert result.resolution_status == "SUPERSEDES_CHAIN_CONFLICT"
    assert any(issue.issue_type == "SUPERSEDES_TARGET_MISSING" for issue in result.issues)


def test_us_id_order_does_not_select_latest() -> None:
    result = resolver().resolve(current_candidates("vg:us-order"))
    assert result.resolution_status == "NO_CONFIRMED_CURRENT"
    assert result.current_candidate_id is None


def test_document_version_order_does_not_select_latest() -> None:
    result = resolver().resolve([
        make_candidate("vg:doc-order", "m:do:v1", "v1", "UNKNOWN", None),
        make_candidate("vg:doc-order", "m:do:v2", "v2", "UNKNOWN", None),
    ])
    assert result.resolution_status == "NO_CONFIRMED_CURRENT"


def test_weak_change_word_does_not_create_supersedes() -> None:
    result = resolver().resolve(current_candidates("vg:weak-change"))
    assert result.resolution_status == "NO_CONFIRMED_CURRENT"
    assert result.current_candidate_id is None


def test_missing_evidence_prevents_confirmed_current() -> None:
    result = resolver().resolve(current_candidates("vg:missing-evidence"))
    assert result.resolution_status == "NO_CONFIRMED_CURRENT"
    assert result.safe_for_deterministic_answer is False


def test_as_of_time_selects_matching_version() -> None:
    result = resolver().resolve(current_candidates("vg:asof"), as_of_time="2024-06-01")
    assert result.resolution_status == "AS_OF_MATCH"
    assert result.current_candidate_id == "m:as:v1"


def test_as_of_overlap_is_conflict() -> None:
    result = resolver().resolve(current_candidates("vg:overlap"), as_of_time="2025-03-01")
    assert result.resolution_status == "VALID_TIME_OVERLAP"
    assert result.safe_for_deterministic_answer is False


def test_as_of_no_match_is_reported() -> None:
    result = resolver().resolve(current_candidates("vg:asof"), as_of_time="2023-01-01")
    assert result.resolution_status == "AS_OF_NO_MATCH"


def test_upload_time_is_not_used_as_business_valid_time() -> None:
    result = resolver().resolve([
        make_candidate("vg:no-valid-time", "m:nv:v1", "v1", "CURRENT", False, valid_from=None, valid_to=None),
    ], as_of_time="2025-01-01")
    assert result.resolution_status == "AS_OF_NO_MATCH"
