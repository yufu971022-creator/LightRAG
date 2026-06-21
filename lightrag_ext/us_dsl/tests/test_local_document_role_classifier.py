from __future__ import annotations

from lightrag_ext.us_dsl.local_document_role_classifier import classify_local_document_role, role_is_canonical_fact_source


def test_quality_annotation_is_not_canonical_fact_source() -> None:
    role = classify_local_document_role("FX_US_质检问题高亮版_v9.2.docx")
    assert role == "QUALITY_ANNOTATION"
    assert role_is_canonical_fact_source(role) is False


def test_synthetic_change_set_is_used_for_version_stress() -> None:
    assert classify_local_document_role("LC_Acceptable_Bank_66US_with_synthetic_modification_US.md") == "SYNTHETIC_CHANGE_SET"


def test_dfx_variant_is_treated_as_version_or_design_variant() -> None:
    assert classify_local_document_role("FX_US_优化后全套US_v9.2_dfx.docx") == "DFX_VARIANT"
