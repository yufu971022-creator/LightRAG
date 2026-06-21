from __future__ import annotations

from lightrag_ext.us_dsl.term_lexical_normalizer import lexical_key, normalize_term


def test_unicode_nfkc_normalization():
    assert lexical_key("ＳＷＩＦＴＣＯＤＥ") == "swiftcode"


def test_case_whitespace_punctuation_variants():
    keys = {lexical_key(value) for value in ["SWIFTCODE", "SWIFT CODE", "swift-code", "swift_code"]}
    assert keys == {"swiftcode"}


def test_lexical_normalization_preserves_business_digits():
    result = normalize_term("Status 2.0")
    assert "2" in result.lexical_key
    assert "0" in result.lexical_key


def test_original_term_is_preserved():
    result = normalize_term(" Swift Code ")
    assert result.original_term == " Swift Code "
    assert result.normalized_term == "swift code"
