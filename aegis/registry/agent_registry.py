"""Agent Registry — Contract 1, Contract 2 §2.4.

Single source of truth for all agent specifications in the Aegis runtime.
Supports registration with validation, lookup by ID, query by capability,
query by output type, and version history tracking.

The registry is consumed by:
- Router: query_by_capability, get (for filter/score phase)
- Orchestrator: query_by_output (for depends_on resolution)
- Governor: get (for tool/trust checks at admission)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aegis.models.agent_spec import AgentSpec
from aegis.models.enums import AgentStatus, VersionBump
from aegis.registry.capability_vocabulary import CapabilityVocabulary
from aegis.registry.schema_validator import SchemaValidator
from aegis.registry.spec_diff import classify_diff, validate_version_bump


@dataclass
class RegistrationResult:
    """Result of an agent registration attempt."""
    success: bool
    agent_id: str = ""
    version: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_update: bool = False


class AgentRegistry:
    """Core registry for agent specifications.

    Maintains the canonical set of agent specs with full validation,
    capability indexing, and version history.

    Thread safety: Not thread-safe. Wrap in a lock if used concurrently.
    """

    def __init__(
        self,
        validator: SchemaValidator,
        vocabulary: CapabilityVocabulary,
    ) -> None:
        self._validator = validator
        self._vocabulary = vocabulary

        # Primary storage: agent_id → current AgentSpec
        self._agents: dict[str, AgentSpec] = {}

        # Version history: agent_id → list of all registered versions (ordered)
        self._history: dict[str, list[AgentSpec]] = {}

        # Capability index: capability → set of agent_ids
        self._capability_index: dict[str, set[str]] = {}

        # Output index: output_type → set of agent_ids
        self._output_index: dict[str, set[str]] = {}

    def register(self, spec: AgentSpec) -> RegistrationResult:
        """Validate and register an agent spec.

        Validates:
        - JSON Schema conformance (structural)
        - agent_id uniqueness (or valid version update)
        - Version increment rules (if updating existing)
        - Capabilities against controlled vocabulary
        - Output schemas resolvability

        Args:
            spec: The agent specification to register.

        Returns:
            RegistrationResult indicating success or failure with details.
        """
        errors: list[str] = []
        warnings: list[str] = []
        is_update = False

        # Run schema validation
        validation = self._validator.validate(spec)
        errors.extend(validation.errors)
        warnings.extend(validation.warnings)

        # Check for existing agent
        existing = self._agents.get(spec.agent_id)

        if existing:
            is_update = True

            # Validate version bump
            bump_valid, bump_reason = validate_version_bump(existing, spec)
            if not bump_valid:
                errors.append(bump_reason)
        else:
            # New agent — check for ID uniqueness (already ensured by dict,
            # but check history for deregistered agents)
            pass

        if errors:
            return RegistrationResult(
                success=False,
                agent_id=spec.agent_id,
                version=spec.version,
                errors=errors,
                warnings=warnings,
                is_update=is_update,
            )

        # Registration succeeds — update indexes
        if existing:
            self._remove_from_indexes(existing)

        self._agents[spec.agent_id] = spec

        # Append to history
        if spec.agent_id not in self._history:
            self._history[spec.agent_id] = []
        self._history[spec.agent_id].append(spec)

        # Update indexes
        self._add_to_indexes(spec)

        return RegistrationResult(
            success=True,
            agent_id=spec.agent_id,
            version=spec.version,
            errors=[],
            warnings=warnings,
            is_update=is_update,
        )

    def get(self, agent_id: str) -> AgentSpec | None:
        """Lookup by exact agent_id.

        Returns None if agent not found or has been deregistered.
        """
        return self._agents.get(agent_id)

    def query_by_capability(
        self,
        required: list[str],
        status_filter: list[AgentStatus] | None = None,
    ) -> list[AgentSpec]:
        """Find agents matching ALL required capabilities.

        Filters by status (default: ACTIVE only).
        Returns full specs for router consumption.

        Args:
            required: All capabilities the agent must have.
            status_filter: Acceptable statuses. Default [ACTIVE].

        Returns:
            List of matching AgentSpecs.
        """
        if status_filter is None:
            status_filter = [AgentStatus.ACTIVE]

        if not required:
            # No capability filter — return all agents matching status
            return [
                spec for spec in self._agents.values()
                if spec.status in status_filter
            ]

        # Find agents that have ALL required capabilities
        candidate_ids: set[str] | None = None
        for cap in required:
            agents_with_cap = self._capability_index.get(cap, set())
            if candidate_ids is None:
                candidate_ids = set(agents_with_cap)
            else:
                candidate_ids &= agents_with_cap

        if not candidate_ids:
            return []

        return [
            self._agents[aid]
            for aid in candidate_ids
            if aid in self._agents and self._agents[aid].status in status_filter
        ]

    def query_by_output(self, output_type: str) -> list[AgentSpec]:
        """Find agents that produce a given output type.

        Used by orchestrator to resolve depends_on chains.

        Args:
            output_type: The output type name to search for.

        Returns:
            List of active AgentSpecs that declare this output.
        """
        agent_ids = self._output_index.get(output_type, set())
        return [
            self._agents[aid]
            for aid in agent_ids
            if aid in self._agents and self._agents[aid].status == AgentStatus.ACTIVE
        ]

    def deregister(self, agent_id: str) -> bool:
        """Remove agent from registry.

        Does not delete spec history — version history remains accessible.

        Returns True if agent was found and removed, False if not found.
        """
        spec = self._agents.pop(agent_id, None)
        if spec is None:
            return False

        self._remove_from_indexes(spec)
        return True

    def get_version_history(self, agent_id: str) -> list[AgentSpec]:
        """Return all registered versions of an agent, ordered by registration time.

        Includes versions from before deregistration.
        """
        return list(self._history.get(agent_id, []))

    def list_agents(
        self,
        status_filter: list[AgentStatus] | None = None,
    ) -> list[AgentSpec]:
        """Return all registered agents, optionally filtered by status."""
        if status_filter is None:
            return list(self._agents.values())
        return [
            spec for spec in self._agents.values()
            if spec.status in status_filter
        ]

    def __len__(self) -> int:
        """Number of currently registered agents."""
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents

    # --- Private index management ---

    def _add_to_indexes(self, spec: AgentSpec) -> None:
        """Add agent to capability and output indexes."""
        for cap in spec.capabilities:
            if cap not in self._capability_index:
                self._capability_index[cap] = set()
            self._capability_index[cap].add(spec.agent_id)

        for output in spec.outputs:
            if output not in self._output_index:
                self._output_index[output] = set()
            self._output_index[output].add(spec.agent_id)

    def _remove_from_indexes(self, spec: AgentSpec) -> None:
        """Remove agent from capability and output indexes."""
        for cap in spec.capabilities:
            if cap in self._capability_index:
                self._capability_index[cap].discard(spec.agent_id)
                if not self._capability_index[cap]:
                    del self._capability_index[cap]

        for output in spec.outputs:
            if output in self._output_index:
                self._output_index[output].discard(spec.agent_id)
                if not self._output_index[output]:
                    del self._output_index[output]
