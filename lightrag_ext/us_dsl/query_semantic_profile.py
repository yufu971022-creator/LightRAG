from __future__ import annotations

import re
from typing import Any

from .hybrid_retrieval_types import HybridRetrievalRequest, QuerySemanticProfile
from .term_query_expander import expand_query_terms
from .version_query_intent import detect_version_query_intent
from .version_retrieval_types import VersionQueryRequest

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")


def build_query_semantic_profile(
    request: HybridRetrievalRequest,
    *,
    term_registry: Any | None = None,
) -> QuerySemanticProfile:
    query_terms = _tokenize(request.query_text)
    canonical_terms: list[str]
    confirmed_aliases: list[str]
    candidate_aliases: list[str]
    rejected_aliases: list[str]
    scope_key: str | None = None
    reasons: list[str] = []
    if term_registry is not None:
        expansion = expand_query_terms(
            query_terms,
            module_code=request.module_code,
            domain_code=request.domain_code,
            feature_key=request.feature_key,
            object_type=request.object_type,
            registry=term_registry,
        )
        canonical_terms = list(expansion.canonical_terms)
        confirmed_aliases = list(expansion.confirmed_aliases)
        candidate_aliases = list(expansion.candidate_aliases)
        rejected_aliases = list(expansion.rejected_aliases)
        scope_key = expansion.scope_used
        reasons.append("TERM_EXPANDER_REUSED")
    else:
        canonical_terms = sorted({term.casefold() for term in query_terms})
        confirmed_aliases = []
        candidate_aliases = []
        rejected_aliases = []
        reasons.append("TOKEN_FALLBACK_USED")

    version_request = VersionQueryRequest(
        query_text=request.query_text,
        explicit_intent=request.explicit_version_intent,  # type: ignore[arg-type]
        as_of_time=request.as_of_time,
        include_historical=request.include_historical,
        module_code=request.module_code,
        domain_code=request.domain_code,
        feature_key=request.feature_key,
        object_type=request.object_type,
    )
    version_intent = detect_version_query_intent(version_request)
    reasons.append("VERSION_INTENT_REUSED")

    domain_hints = [request.domain_code] if request.domain_code else []
    feature_hints = [request.feature_key] if request.feature_key else []
    object_type_hints = [request.object_type] if request.object_type else []
    if request.strict_scope:
        reasons.append("STRICT_SCOPE_EXPLICIT")
    elif domain_hints or feature_hints:
        reasons.append("SCOPE_HINT_NOT_FILTER")

    return QuerySemanticProfile(
        query_text=request.query_text,
        task_type=request.task_type,
        canonical_terms=canonical_terms,
        confirmed_aliases=confirmed_aliases,
        candidate_aliases=candidate_aliases,
        rejected_aliases=rejected_aliases,
        version_intent=version_intent,
        domain_hints=domain_hints,
        feature_hints=feature_hints,
        object_type_hints=object_type_hints,
        strict_scope=request.strict_scope,
        scope_key=scope_key,
        reason_codes=reasons,
    )


def _tokenize(text: str) -> list[str]:
    return [match.group(0) for match in _TOKEN_RE.finditer(text) if match.group(0)]
