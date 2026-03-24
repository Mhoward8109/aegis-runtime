"""Test registry CRUD operations — Contract 1 §1.3.

Tests registration, deregistration, version updates, and duplicate handling.
"""

import pytest

from aegis.models.agent_spec import AgentSpec
from aegis.models.enums import AgentStatus
from aegis.registry.agent_registry import AgentRegistry
from aegis.registry.capability_vocabulary import CapabilityVocabulary
from aegis.registry.schema_validator import SchemaValidator
from aegis.tests.fixtures import (
    valid_agent_spec,
    valid_backend_agent_spec,
    deprecated_agent_spec,
)


@pytest.fixture
def vocabulary() -> CapabilityVocabulary:
    return CapabilityVocabulary()


@pytest.fixture
def validator(vocabulary: CapabilityVocabulary) -> SchemaValidator:
    return SchemaValidator(vocabulary=vocabulary, schema_base_path=None)


@pytest.fixture
def registry(validator: SchemaValidator, vocabulary: CapabilityVocabulary) -> AgentRegistry:
    return AgentRegistry(validator=validator, vocabulary=vocabulary)


class TestRegisterAndGet:
    """Basic register → get roundtrip."""

    def test_register_valid_spec(self, registry: AgentRegistry):
        spec = valid_agent_spec()
        result = registry.register(spec)
        assert result.success is True
        assert result.agent_id == spec.agent_id
        assert result.is_update is False

    def test_get_registered_agent(self, registry: AgentRegistry):
        spec = valid_agent_spec()
        registry.register(spec)
        retrieved = registry.get(spec.agent_id)
        assert retrieved is not None
        assert retrieved.agent_id == spec.agent_id
        assert retrieved.version == spec.version

    def test_get_nonexistent_returns_none(self, registry: AgentRegistry):
        assert registry.get("nonexistent.agent") is None

    def test_registry_length(self, registry: AgentRegistry):
        assert len(registry) == 0
        registry.register(valid_agent_spec())
        assert len(registry) == 1
        registry.register(valid_backend_agent_spec())
        assert len(registry) == 2

    def test_contains(self, registry: AgentRegistry):
        spec = valid_agent_spec()
        assert spec.agent_id not in registry
        registry.register(spec)
        assert spec.agent_id in registry


class TestDuplicateRejection:
    """Same agent_id cannot be registered twice without version bump."""

    def test_same_version_rejected(self, registry: AgentRegistry):
        spec = valid_agent_spec()
        registry.register(spec)

        # Try to register same agent_id + same version
        result = registry.register(spec)
        assert result.success is False
        assert "already registered" in result.errors[0].lower()


class TestVersionUpdate:
    """Higher version of existing agent replaces previous."""

    def test_minor_bump_accepted(self, registry: AgentRegistry):
        spec_v1 = valid_agent_spec()
        registry.register(spec_v1)

        # Create v1.1.0 with additive change (new capability)
        spec_v2 = valid_agent_spec()
        spec_v2.capabilities = list(spec_v1.capabilities) + ["write_tests"]
        # Bypass __post_init__ by creating fresh
        spec_v2 = AgentSpec(
            agent_id=spec_v1.agent_id,
            version="1.1.0",
            status=spec_v1.status,
            role=spec_v1.role,
            capabilities=list(spec_v1.capabilities) + ["write_tests"],
            required_inputs=list(spec_v1.required_inputs),
            optional_inputs=list(spec_v1.optional_inputs),
            outputs=list(spec_v1.outputs),
            tools=list(spec_v1.tools),
            constraints=list(spec_v1.constraints),
            evaluation=spec_v1.evaluation,
        )

        result = registry.register(spec_v2)
        assert result.success is True
        assert result.is_update is True
        assert result.version == "1.1.0"

        # Verify updated
        retrieved = registry.get(spec_v1.agent_id)
        assert retrieved is not None
        assert retrieved.version == "1.1.0"

    def test_version_history_preserved(self, registry: AgentRegistry):
        spec_v1 = valid_agent_spec()
        registry.register(spec_v1)

        spec_v2 = AgentSpec(
            agent_id=spec_v1.agent_id,
            version="1.1.0",
            status=spec_v1.status,
            role=spec_v1.role,
            capabilities=list(spec_v1.capabilities) + ["write_tests"],
            required_inputs=list(spec_v1.required_inputs),
            optional_inputs=list(spec_v1.optional_inputs),
            outputs=list(spec_v1.outputs),
            tools=list(spec_v1.tools),
            constraints=list(spec_v1.constraints),
            evaluation=spec_v1.evaluation,
        )
        registry.register(spec_v2)

        history = registry.get_version_history(spec_v1.agent_id)
        assert len(history) == 2
        assert history[0].version == "1.0.0"
        assert history[1].version == "1.1.0"


class TestDeregistration:
    """Deregistration removes from active but preserves history."""

    def test_deregister_removes_from_active(self, registry: AgentRegistry):
        spec = valid_agent_spec()
        registry.register(spec)
        assert registry.get(spec.agent_id) is not None

        result = registry.deregister(spec.agent_id)
        assert result is True
        assert registry.get(spec.agent_id) is None
        assert len(registry) == 0

    def test_deregister_preserves_history(self, registry: AgentRegistry):
        spec = valid_agent_spec()
        registry.register(spec)
        registry.deregister(spec.agent_id)

        history = registry.get_version_history(spec.agent_id)
        assert len(history) == 1
        assert history[0].version == "1.0.0"

    def test_deregister_nonexistent_returns_false(self, registry: AgentRegistry):
        assert registry.deregister("nonexistent.agent") is False

    def test_deregister_removes_from_capability_index(self, registry: AgentRegistry):
        spec = valid_agent_spec()
        registry.register(spec)

        # Should find by capability before deregistration
        found = registry.query_by_capability(["build_ui"])
        assert len(found) == 1

        registry.deregister(spec.agent_id)

        # Should not find after deregistration
        found = registry.query_by_capability(["build_ui"])
        assert len(found) == 0


class TestListAgents:
    """List all registered agents with optional status filter."""

    def test_list_all(self, registry: AgentRegistry):
        registry.register(valid_agent_spec())
        registry.register(valid_backend_agent_spec())
        registry.register(deprecated_agent_spec())

        all_agents = registry.list_agents()
        assert len(all_agents) == 3

    def test_list_by_status(self, registry: AgentRegistry):
        registry.register(valid_agent_spec())
        registry.register(deprecated_agent_spec())

        active = registry.list_agents(status_filter=[AgentStatus.ACTIVE])
        assert len(active) == 1
        assert active[0].status == AgentStatus.ACTIVE

        deprecated = registry.list_agents(status_filter=[AgentStatus.DEPRECATED])
        assert len(deprecated) == 1
        assert deprecated[0].status == AgentStatus.DEPRECATED
