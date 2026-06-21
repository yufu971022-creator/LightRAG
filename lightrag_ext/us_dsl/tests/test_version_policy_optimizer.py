from __future__ import annotations

from pathlib import Path

from lightrag_ext.us_dsl.version_policy_optimizer import (
    build_optimized_version_relations,
    optimized_version_relation_policy,
)
from lightrag_ext.us_dsl.version_relation_builder import build_version_relations
from lightrag_ext.us_dsl.version_relation_policy import VersionRelationPolicy
from lightrag_ext.us_dsl.version_relation_types import VersionedSemanticObject


def test_singleton_no_conflict_not_review_required():
    _nodes, relations, report = build_optimized_version_relations([_object("Field A")])

    assert report.version_review_required_count == 0
    assert all(item.relation_type != "VersionReviewRequired" for item in relations)


def test_singleton_no_conflict_has_version():
    _nodes, relations, report = build_optimized_version_relations([_object("Field A")])

    assert report.has_version_count == 1
    assert any(item.relation_type == "HasVersion" for item in relations)


def test_singleton_not_formal_current():
    nodes, _relations, _report = build_optimized_version_relations([_object("Field A")])

    assert nodes[0].version_status == "SingleVersionNoConflict"
    assert nodes[0].metadata["safeToFormalGraph"] is False


def test_explicit_current_not_review_required():
    _nodes, _relations, report = build_optimized_version_relations(
        [_object("Field A", latest_flag=True)]
    )

    assert report.version_review_required_count == 0


def test_multiple_latest_flags_review_required():
    first = _object("Field A", rule_version="v1", latest_flag=True)
    second = _object("Field A", rule_version="v2", latest_flag=True)

    _nodes, _relations, report = build_optimized_version_relations([first, second])

    assert report.version_review_required_count > 0


def test_weak_keyword_without_target_review_required():
    _nodes, relations, report = build_optimized_version_relations(
        [_object("Field A", evidence_text="Field A 调整 display rule.")]
    )

    assert report.supersedes_count == 0
    assert report.version_review_required_count == 1
    assert any(item.reason_code == "WEAK_VERSION_KEYWORD_ONLY" for item in relations)


def test_explicit_supersedes_still_required_for_supersedes():
    unsafe = _object("Field A", rule_version="v2", supersedes=["v1"])
    explicit = _object(
        "Field B",
        rule_version="v2",
        supersedes=["v1"],
        raw={"supersedes": ["v1"]},
    )

    _nodes, _relations, unsafe_report = build_optimized_version_relations([unsafe])
    _nodes, _relations, explicit_report = build_optimized_version_relations([explicit])

    assert unsafe_report.supersedes_count == 0
    assert unsafe_report.unsafe_supersedes_blocked_count == 1
    assert explicit_report.supersedes_count == 1


def test_no_source_order_supersedes():
    older = _object("Field A", source_us_id="US-001", rule_version="v1")
    newer = _object("Field A", source_us_id="US-002", rule_version="v2")

    _nodes, _relations, report = build_optimized_version_relations([older, newer])

    assert report.supersedes_count == 0


def test_conflict_without_supersedes_review_required():
    first = _object("Field A", rule_text="Field A is editable.", rule_version="v1")
    second = _object("Field A", rule_text="Field A is readonly.", rule_version="v2")

    _nodes, _relations, report = build_optimized_version_relations([first, second])

    assert report.version_conflict_count > 0
    assert report.version_review_required_count > 0


def test_missing_evidence_blocks_version_safe():
    missing = _object("Field A", text_unit_id=None)

    _nodes, _relations, report = build_optimized_version_relations([missing])

    assert report.has_version_count == 0
    assert report.missing_evidence_count == 1


def test_version_group_key_granularity_feature_and_dimension():
    different_feature = [
        _object("Field A", feature_key="FeatureA", rule_text="Field A is editable."),
        _object("Field A", feature_key="FeatureB", rule_text="Field A is readonly."),
    ]
    different_dimension = [
        _object("Field B", rule_dimension="editable_rule", rule_text="Field B is editable."),
        _object("Field B", rule_dimension="display_rule", rule_text="Field B is readonly."),
    ]

    _nodes, _relations, feature_report = build_optimized_version_relations(different_feature)
    _nodes, _relations, dimension_report = build_optimized_version_relations(different_dimension)

    assert feature_report.version_conflict_count == 0
    assert dimension_report.version_conflict_count == 0


def test_before_policy_reviews_singleton_unknown():
    before_policy = VersionRelationPolicy(
        allow_singleton_no_conflict_as_test_safe=False,
        allow_explicit_current_as_test_safe=False,
        generate_version_review_for_singleton=True,
    )

    _nodes, _relations, report = build_version_relations(
        [_object("Field A")],
        policy=before_policy,
    )

    assert report.version_review_required_count == 1


def test_no_lc_hardcode_in_version_policy_optimizer():
    root = Path(__file__).resolve().parents[1]
    forbidden_terms = [
        "LCAB",
        "Acceptable Bank",
        "可接受银行",
        "Bank Status",
        "Swift Code",
        "Transfer To",
    ]
    for relative_path in [
        "version_policy_optimizer.py",
        "version_relation_policy.py",
        "version_relation_builder.py",
    ]:
        text = (root / relative_path).read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in text


def test_optimizer_config_defaults():
    policy = optimized_version_relation_policy()

    assert policy.allow_singleton_no_conflict_as_test_safe is True
    assert policy.allow_weak_keyword_supersedes is False
    assert policy.require_explicit_supersedes_evidence is True


def _object(
    object_key: str,
    *,
    feature_key: str = "FeatureA",
    rule_dimension: str = "field_rule",
    source_us_id: str = "US-001",
    text_unit_id: str | None = "tu-1",
    evidence_text: str = "Field A is editable.",
    rule_text: str | None = None,
    rule_version: str | None = None,
    latest_flag: bool | None = None,
    supersedes: list[str] | None = None,
    raw: dict | None = None,
) -> VersionedSemanticObject:
    group_key = "|".join(
        [
            "m",
            "ledger",
            feature_key.lower(),
            "fieldspec",
            object_key.lower(),
            rule_dimension.lower(),
        ]
    )
    return VersionedSemanticObject(
        version_group_key=group_key,
        module_code="M",
        domain_code="Ledger",
        feature_key=feature_key,
        object_type="FieldSpec",
        object_key=object_key,
        rule_dimension=rule_dimension,
        source_us_id=source_us_id,
        source_text_unit_id=text_unit_id,
        section_type="field_table",
        evidence_text=evidence_text,
        source_span={"start": 0, "end": 10},
        text_hash=f"hash-{object_key}-{rule_version or text_unit_id or 'missing'}",
        rule_text=rule_text or evidence_text,
        latest_flag=latest_flag,
        version_status=None,
        rule_version=rule_version,
        supersedes=supersedes or [],
        version_keywords=[],
        raw={
            "sourceUsId": source_us_id,
            "textUnitId": text_unit_id,
            "textHash": f"hash-{object_key}-{rule_version or text_unit_id or 'missing'}",
            "evidenceText": evidence_text,
            **(raw or {}),
        },
    )
