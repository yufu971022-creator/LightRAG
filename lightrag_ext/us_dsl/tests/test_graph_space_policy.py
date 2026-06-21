from __future__ import annotations

import pytest

from lightrag_ext.us_dsl.graph_space_policy import (
    GraphSpaceDescriptor,
    GraphSpacePolicyError,
    generic_descriptor,
    issue_descriptor,
    pfss_descriptor,
    validate_graph_space_descriptor,
    validate_graph_space_isolation,
)


def test_pfss_namespace_must_be_test_only():
    validate_graph_space_descriptor(pfss_descriptor())
    with pytest.raises(GraphSpacePolicyError):
        validate_graph_space_descriptor(GraphSpaceDescriptor(space=pfss_descriptor().space, workspace="prod", namespace="prod_graph"))


def test_generic_namespace_must_be_isolated():
    validate_graph_space_descriptor(generic_descriptor())
    with pytest.raises(GraphSpacePolicyError):
        validate_graph_space_descriptor(GraphSpaceDescriptor(space=generic_descriptor().space, workspace="pfss_test", namespace="pfss_test_graph"))


def test_issue_space_is_not_pfss_graph():
    validate_graph_space_descriptor(issue_descriptor())
    with pytest.raises(GraphSpacePolicyError):
        validate_graph_space_descriptor(issue_descriptor(workspace="pfss_test_issue", namespace="pfss_test_graph"))


def test_namespace_collision_is_blocked():
    pfss = pfss_descriptor(workspace="shared_pfss_test", namespace="shared_pfss_test_graph")
    generic = generic_descriptor(workspace="shared_pfss_test", namespace="shared_pfss_test_graph", write_enabled=True)

    with pytest.raises(GraphSpacePolicyError, match="FAIL_GRAPH_SPACE_COLLISION"):
        validate_graph_space_isolation([pfss, generic])
