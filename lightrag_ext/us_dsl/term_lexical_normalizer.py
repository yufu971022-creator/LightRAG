from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_CONNECTORS = "-_‐‑‒–—―﹘﹣－/\\"
_CONNECTOR_RE = re.compile(f"[{re.escape(_CONNECTORS)}]+")
_SPACE_RE = re.compile(r"\s+")
_STRIP_PUNCT_RE = re.compile(r"[\s_\-‐‑‒–—―﹘﹣－/\\.,;:()\[\]{}'\"`]+")


@dataclass(frozen=True)
class LexicalNormalizationResult:
    original_term: str
    normalized_term: str
    lexical_key: str


def normalize_term(term: str) -> LexicalNormalizationResult:
    original = term
    normalized = unicodedata.normalize("NFKC", term).strip()
    normalized = _CONNECTOR_RE.sub(" ", normalized)
    normalized = _SPACE_RE.sub(" ", normalized).strip()
    normalized = normalized.casefold()
    lexical_key = _STRIP_PUNCT_RE.sub("", normalized)
    return LexicalNormalizationResult(original_term=original, normalized_term=normalized, lexical_key=lexical_key)


def lexical_key(term: str) -> str:
    return normalize_term(term).lexical_key


def canonical_key(term: str) -> str:
    return lexical_key(term)
