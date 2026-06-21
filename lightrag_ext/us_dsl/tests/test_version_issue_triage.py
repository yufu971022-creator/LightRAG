from __future__ import annotations

import json
from pathlib import Path

from lightrag_ext.us_dsl.version_issue_triage import (
    build_lc_version_issue_triage_report,
    build_version_issue_triage_report,
    serialize_version_issue_triage_report,
)
from lightrag_ext.us_dsl.version_relation_types import VersionedSemanticObject


def test_version_issue_triage_report_counts():
    report = build_version_issue_triage_report(
        [
            _object("Field A"),
            _object("Field B", latest_flag=True),
            _object("Field C", evidence_text="Field C 调整 rule."),
            _object("Field D", rule_text="Field D is editable.", rule_version="v1"),
            _object("Field D", rule_text="Field D is readonly.", rule_version="v2"),
        ]
    )

    assert report.total_version_groups == 4
    assert report.singleton_no_conflict_count == 1
    assert report.explicit_current_count == 1
    assert report.weak_version_keyword_only_count == 1
    assert report.conflict_without_supersedes_count == 1
    assert report.review_required_after_count == 2


def test_lc_version_review_required_reduced():
    report = build_lc_version_issue_triage_report()

    assert report.review_required_before_count >= report.review_required_after_count
    assert report.review_required_after_count < 14
    assert report.review_required_reduction_count > 0
    assert report.true_review_required_count == report.review_required_after_count


def test_no_unsafe_supersedes_generated():
    report = build_lc_version_issue_triage_report()

    assert report.unsafe_supersedes_blocked_count == 0


def test_no_lc_hardcode_in_version_triage():
    root = Path(__file__).resolve().parents[1]
    forbidden_terms = [
        "LCAB",
        "Acceptable Bank",
        "可接受银行",
        "Bank Status",
        "Swift Code",
        "Transfer To",
    ]
    text = (root / "version_issue_triage.py").read_text(encoding="utf-8")
    for term in forbidden_terms:
        assert term not in text


def test_report_serializable():
    report = build_version_issue_triage_report([_object("Field A")])

    json.dumps(serialize_version_issue_triage_report(report))


def _object(
    object_key: str,
    *,
    feature_key: str = "FeatureA",
    rule_dimension: str = "field_rule",
    source_us_id: str = "US-001",
    text_unit_id: str = "tu-1",
    evidence_text: str = "Field A is editable.",
    rule_text: str | None = None,
    rule_version: str | None = None,
    latest_flag: bool | None = None,
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
        text_hash=f"hash-{object_key}-{rule_version or 'one'}",
        rule_text=rule_text or evidence_text,
        latest_flag=latest_flag,
        version_status=None,
        rule_version=rule_version,
        supersedes=[],
        version_keywords=[],
        raw={
            "sourceUsId": source_us_id,
            "textUnitId": text_unit_id,
            "textHash": f"hash-{object_key}-{rule_version or 'one'}",
            "evidenceText": evidence_text,
        },
    )
