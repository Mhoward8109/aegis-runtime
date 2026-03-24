"""Test capability lookup — Contract 1 §1.3, Contract 2 §2.3.

Tests registry query operations: query by capability, query by output type,
status filtering in queries.
"""

import pytest

from aegis.models.enums import AgentStatus
from aegis.registry.agent_registry import AgentRegistry
from aegis.registry.capability_vocabulary import CapabilityVocabulary
from aegis.registry.schema_validator import SchemaValidator
from aegis.tests.fixtures import (
    valid_agent_spec,
    valid_backend_agent_spec,
    valid_research_agent_spec,
    deprecated_agent_spec,
    suspended_agent_spec,
)


@pytest.fixture
def vocabulary() -> CapabilityVocabulary:
    return CapabilityVocabulary()


@pytest.fixture
def registry(vocabulary: CapabilityVocabulary) -> AgentRegistry:
    validator = SchemaValidator(vocabulary=vocabulary, schema_base_path=None)
    reg = AgentRegistry(validator=validator, vocabulary=vocabulary)
    # Pre-populate with test agents
    reg.register(valid_agent_spec())          # build_ui, optimize_rendering, integrate_api
    reg.register(valid_backend_agent_spec())   # write_backend, design_schema, integrate_api
    reg.register(valid_research_agent_spec())  # synthesize_research, analyze_data
    reg.register(deprecated_agent_spec())      # generate_report (deprecated)
    reg.register(suspended_agent_spec())       # write_tests (suspended)
    return reg


class TestQuerySingleCapability:
    """Query with a single required capability."""

    def test_finds_matching_agents(self, registry: AgentRegistry):
        results = registry.query_by_capability(["integrate_api"])
        assert len(results) == 2
        ids = {r.agent_id for r in results}
        assert "engineering.frontend-developer" in ids
        assert "engineering.backend-architect" in ids

    def test_unique_capability_returns_one(self, registry: AgentRegistry):
        results = registry.query_by_capability(["build_ui"])
        assert len(results) == 1
        assert results[0].agent_id == "engineering.frontend-developer"


class TestQueryMultipleCapabilities:
    """Query requiring intersection of multiple capabilities."""

    def test_intersection_narrows_results(self, registry: AgentRegistry):
        # Both frontend and backend have integrate_api, but only frontend has build_ui
        results = registry.query_by_capability(["integrate_api", "build_ui"])
        assert len(results) == 1
        assert results[0].agent_id == "engineering.frontend-developer"

    def test_no_agent_has_all(self, registry: AgentRegistry):
        # No single agent has both build_ui and write_backend
        results = registry.query_by_capability(["build_ui", "write_backend"])
        assert len(results) == 0


class TestQueryFiltersByStatus:
    """Deprecated and suspended agents filtered by default."""

    def test_default_filter_excludes_deprecated(self, registry: AgentRegistry):
        # deprecated agent has generate_report
        results = registry.query_by_capability(["generate_report"])
        assert len(results) == 0  # filtered out because deprecated

    def test_explicit_deprecated_filter(self, registry: AgentRegistry):
        results = registry.query_by_capability(
            ["generate_report"],
            status_filter=[AgentStatus.DEPRECATED],
        )
        assert len(results) == 1
        assert results[0].status == AgentStatus.DEPRECATED

    def test_suspended_never_in_default(self, registry: AgentRegistry):
        results = registry.query_by_capability(["write_tests"])
        assert len(results) == 0  # suspended agent filtered

    def test_multi_status_filter(self, registry: AgentRegistry):
        results = registry.query_by_capability(
            ["generate_report"],
            status_filter=[AgentStatus.ACTIVE, AgentStatus.DEPRECATED],
        )
        assert len(results) == 1


class TestQueryUnknownCapability:
    """Querying for capabilities no agent has."""

    def test_returns_empty_list(self, registry: AgentRegistry):
        results = registry.query_by_capability(["teleport_users"])
        assert results == []


class TestQueryByOutput:
    """Query agents by output type — used by orchestrator for depends_on."""

    def test_finds_producer(self, registry: AgentRegistry):
        results = registry.query_by_output("ui_code")
        assert len(results) == 1
        assert results[0].agent_id == "engineering.frontend-developer"

    def test_shared_output_type(self, registry: AgentRegistry):
        # Both frontend and backend can produce api_schema? No — only backend.
        # frontend outputs: ui_code, component_structure
        # backend outputs: backend_code, api_schema
        results = registry.query_by_output("api_schema")
        assert len(results) == 1
        assert results[0].agent_id == "engineering.backend-architect"

    def test_unknown_output_returns_empty(self, registry: AgentRegistry):
        results = registry.query_by_output("nonexistent_output")
        assert results == []

    def test_deprecated_excluded_from_output_query(self, registry: AgentRegistry):
        # deprecated agent outputs formatted_report, but should be excluded
        results = registry.query_by_output("formatted_report")
        assert len(results) == 0


class TestCapabilityVocabulary:
    """Capability vocabulary enforcement."""

    def test_valid_capabilities_pass(self, vocabulary: CapabilityVocabulary):
        result = vocabulary.validate(["build_ui", "integrate_api"])
        assert result.valid is True
        assert result.unknown_capabilities == []

    def test_unknown_capabilities_fail(self, vocabulary: CapabilityVocabulary):
        result = vocabulary.validate(["build_ui", "teleport_users"])
        assert result.valid is False
        assert "teleport_users" in result.unknown_capabilities

    def test_register_new_capability(self, vocabulary: CapabilityVocabulary):
        assert "teleport_users" not in vocabulary
        newly_added = vocabulary.register_capability("teleport_users")
        assert newly_added is True
        assert "teleport_users" in vocabulary

        # Idempotent
        assert vocabulary.register_capability("teleport_users") is False

    def test_list_capabilities_sorted(self, vocabulary: CapabilityVocabulary):
        caps = vocabulary.list_capabilities()
        assert caps == sorted(caps)
        assert len(caps) > 0
