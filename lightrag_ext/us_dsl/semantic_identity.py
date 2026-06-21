from __future__ import annotations

import re

from .term_lexical_normalizer import canonical_key
from .term_normalization_types import SemanticIdentityKey, TermNormalizationDecision, TermScope

_SAFE_RE = re.compile(r"[^a-z0-9]+")


def build_semantic_identity_key(
    decision: TermNormalizationDecision,
    *,
    scope: TermScope,
    object_type: str,
    rule_dimension: str | None = None,
) -> SemanticIdentityKey:
    clean_scope = scope.normalized()
    return SemanticIdentityKey(
        system_name=clean_scope.system_name,
        module_code=clean_scope.module_code,
        domain_code=clean_scope.domain_code,
        feature_key=clean_scope.feature_key,
        object_type=object_type,
        canonical_object_key=decision.canonical_key or canonical_key(decision.canonical_term),
        rule_dimension=rule_dimension,
    )


def stable_semantic_object_id(identity: SemanticIdentityKey) -> str:
    module, domain, feature, object_type, canonical, rule_dimension = [
        _slug(part) for part in [
            identity.module_code or "global",
            identity.domain_code or "domain",
            identity.feature_key or "feature",
            identity.object_type,
            identity.canonical_object_key,
            identity.rule_dimension or "default",
        ]
    ]
    return f"urn:pfss:{module}:{domain}:{feature}:{object_type}:{canonical}:{rule_dimension}"


def stable_semantic_relation_id(
    *,
    src_semantic_object_id: str,
    relation_type: str,
    tgt_semantic_object_id: str,
    relation_scope: str | None = None,
    rule_dimension: str | None = None,
) -> str:
    relation = _slug(relation_type)
    scope = _slug(relation_scope or "default")
    dimension = _slug(rule_dimension or "default")
    return f"urn:pfss:rel:{src_semantic_object_id}:{relation}:{tgt_semantic_object_id}:{scope}:{dimension}"


def stable_version_group_key(identity: SemanticIdentityKey) -> str:
    return "vg:" + "|".join(identity.components())


def _slug(value: str) -> str:
    cleaned = _SAFE_RE.sub("-", str(value).casefold()).strip("-")
    return cleaned or "default"
