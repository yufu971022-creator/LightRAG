from __future__ import annotations

from lightrag_ext.us_dsl.relation_type_signature_registry import default_relation_type_signature_registry


def test_has_report_filter_requires_field_spec_target() -> None:
    registry = default_relation_type_signature_registry()
    assert registry.validate("HasReportFilter", "ReportSpec", "FieldSpec").valid
    invalid = registry.validate("HasReportFilter", "ReportSpec", "Location")
    assert not invalid.valid
    assert invalid.issue_code == "INVALID_RELATION_SIGNATURE"


def test_assigns_handler_requires_task_and_role_types() -> None:
    registry = default_relation_type_signature_registry()
    assert registry.validate("AssignsHandler", "TaskRule", "RolePermission").valid
    assert not registry.validate("AssignsHandler", "ReportSpec", "RolePermission").valid


def test_calls_backend_api_requires_integration_endpoint_target() -> None:
    registry = default_relation_type_signature_registry()
    assert registry.validate("CallsBackendApi", "ReportSpec", "IntegrationEndpoint").valid
    assert not registry.validate("CallsBackendApi", "ReportSpec", "FieldSpec").valid


def test_invalid_relation_signature_creates_issue() -> None:
    validation = default_relation_type_signature_registry().validate("HasReportFilter", "ReportSpec", "Location")
    assert validation.issue_code == "INVALID_RELATION_SIGNATURE"


def test_resolver_does_not_invent_relation_to_fix_signature() -> None:
    registry = default_relation_type_signature_registry()
    validation = registry.validate("UnknownRelation", "ReportSpec", "FieldSpec")
    assert not validation.valid
    assert validation.issue_code == "UNKNOWN_RELATION_SIGNATURE"
