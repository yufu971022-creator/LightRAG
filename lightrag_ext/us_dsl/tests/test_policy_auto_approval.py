from __future__ import annotations

import json

from lightrag_ext.us_dsl.policy_auto_approval import (
    PolicyAutoApprovalConfig,
    evaluate_policy_auto_approval,
    run_policy_auto_approval,
    serialize_policy_auto_approval_result,
)
from lightrag_ext.us_dsl.promotion_types import (
    BLOCKED,
    ELIGIBLE,
    OBJECT_KIND_ENTITY,
    OBJECT_KIND_RELATIONSHIP,
    PromotionCandidate,
)


def test_policy_auto_approval_allows_valid_evidence_object():
    decision = evaluate_policy_auto_approval(_candidate())

    assert decision.approved_for_test_graph is True
    assert decision.approved_for_formal_graph is False
    assert decision.evidence_complete is True
    assert decision.sidecar_ready is True


def test_policy_auto_approval_allows_safe_test_version():
    decision = evaluate_policy_auto_approval(
        _candidate(
            object_kind=OBJECT_KIND_RELATIONSHIP,
            proposed_relation_type="HasVersion",
            src_id="Field A",
            tgt_id="RuleVersion:1",
            source_metadata={
                "relationType": "HasVersion",
                "versionStatus": "SingleVersionNoConflict",
                "requiresHumanReview": False,
            },
        )
    )

    assert decision.approved_for_test_graph is True
    assert decision.approved_for_formal_graph is False


def test_policy_blocks_review_required():
    decision = evaluate_policy_auto_approval(
        _candidate(review_decision="REVIEW_REQUIRED"),
    )

    assert decision.approved_for_test_graph is False
    assert "REVIEW_REQUIRED_BLOCKED" in decision.blocking_reasons


def test_policy_blocks_info_only():
    decision = evaluate_policy_auto_approval(_candidate(review_decision="INFO_ONLY"))

    assert decision.approved_for_test_graph is False
    assert "INFO_ONLY_BLOCKED" in decision.blocking_reasons


def test_policy_blocks_version_review_required():
    decision = evaluate_policy_auto_approval(
        _candidate(
            review_decision="VERSION_REVIEW",
            source_metadata={"reasonCode": "VersionReviewRequired"},
        )
    )

    assert decision.approved_for_test_graph is False
    assert "VERSION_REVIEW_REQUIRED_BLOCKED" in decision.blocking_reasons


def test_policy_blocks_missing_evidence():
    candidate = _candidate(evidence={**_evidence(), "evidenceText": None})

    decision = evaluate_policy_auto_approval(candidate)

    assert decision.approved_for_test_graph is False
    assert "MISSING_EVIDENCE" in decision.blocking_reasons


def test_policy_blocks_invalid_relation():
    decision = evaluate_policy_auto_approval(
        _candidate(
            object_kind=OBJECT_KIND_RELATIONSHIP,
            proposed_relation_type="DependsOn",
            src_id="Field A",
            tgt_id="Field B",
            eligibility_status=BLOCKED,
            blocking_reasons=["INVALID_RELATION"],
        )
    )

    assert decision.approved_for_test_graph is False
    assert "INVALID_RELATION_BLOCKED" in decision.blocking_reasons


def test_policy_blocks_forbidden_relation():
    decision = evaluate_policy_auto_approval(
        _candidate(
            object_kind=OBJECT_KIND_RELATIONSHIP,
            proposed_relation_type="has_child",
            src_id="Field A",
            tgt_id="Field B",
            eligibility_status=BLOCKED,
            blocking_reasons=["FORBIDDEN_RELATION_TYPE"],
        )
    )

    assert decision.approved_for_test_graph is False
    assert "FORBIDDEN_RELATION_TYPE" in decision.blocking_reasons


def test_policy_does_not_approve_formal_graph():
    result = run_policy_auto_approval([_candidate()], config=PolicyAutoApprovalConfig())

    assert result.approved_for_test_graph_count == 1
    assert all(item.approved_for_formal_graph is False for item in result.decisions)
    assert result.manifest.reviewer == "POLICY_AUTO_APPROVAL_TEST_ONLY"


def test_policy_report_serializable():
    result = run_policy_auto_approval([_candidate()])

    json.dumps(serialize_policy_auto_approval_result(result))


def _candidate(
    *,
    object_kind: str = OBJECT_KIND_ENTITY,
    proposed_relation_type: str | None = None,
    src_id: str | None = None,
    tgt_id: str | None = None,
    review_decision: str = "AUTO_ACCEPT_FOR_REPORT",
    evidence: dict | None = None,
    source_metadata: dict | None = None,
    eligibility_status: str = ELIGIBLE,
    blocking_reasons: list[str] | None = None,
) -> PromotionCandidate:
    metadata = {
        "knowledgeStatus": "Candidate",
        "validationStatus": "VALID",
        "reviewDecision": review_decision,
        **(source_metadata or {}),
    }
    return PromotionCandidate(
        candidate_id="candidate-1",
        object_kind=object_kind,
        source_object={"metadata": metadata},
        proposed_entity_name="Field A" if object_kind == OBJECT_KIND_ENTITY else None,
        proposed_entity_type="FieldSpec" if object_kind == OBJECT_KIND_ENTITY else None,
        proposed_relation_type=proposed_relation_type,
        src_id=src_id,
        tgt_id=tgt_id,
        knowledge_status="Candidate",
        review_decision=review_decision,
        validation_status="VALID",
        confidence_score=0.9,
        evidence=evidence or _evidence(),
        version_metadata={},
        term_metadata={},
        eligibility_status=eligibility_status,
        blocking_reasons=blocking_reasons or [],
        required_reviewer_action=None,
        idempotency_key="idem-1",
        rollback_key="rollback-1",
        audit_metadata={"sidecarId": "sidecar-1"},
    )


def _evidence() -> dict:
    return {
        "sourceUsId": "US-001",
        "textUnitId": "tu-1",
        "source_id": "tu-1",
        "sourceSpan": {"start": 0, "end": 10},
        "textHash": "hash-1",
        "evidenceText": "Field A depends on Field B.",
    }
