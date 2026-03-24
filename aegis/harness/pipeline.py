"""Pipeline — End-to-End Integration Harness.

Wires the full path: register agents → submit task → route → dispatch → result.

Usage:

    from aegis.harness import Pipeline

    pipeline = Pipeline()
    pipeline.register_agent(my_agent_spec)
    pipeline.set_trust("my.agent", TrustTier.MEDIUM, "operator")

    result = pipeline.run(
        task_id="task-1",
        required_capabilities=["build_ui"],
        inputs_available=["task_spec"],
        prompt="Build a login form component",
    )

    if result.success:
        print(result.output)
    else:
        print(f"Failed: {result.error}")

This is a thin harness. It does not orchestrate multi-step workflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aegis.models.agent_spec import AgentSpec
from aegis.models.enums import RiskTier, RoutingMode, TrustTier
from aegis.registry.agent_registry import AgentRegistry, RegistrationResult
from aegis.registry.capability_vocabulary import CapabilityVocabulary
from aegis.registry.schema_validator import SchemaValidator
from aegis.registry.trust_registry import TrustRegistry
from aegis.router.router import RouterConfig, route
from aegis.router.task_descriptor import TaskBudget, TaskConstraints, TaskDescriptor
from aegis.router.types import RouteResult, RoutingFailure

from aegis.harness.dispatcher import Dispatcher, DispatcherConfig, ExecutionResult


@dataclass
class PipelineResult:
    """Full pipeline outcome: routing + execution."""
    task_id: str
    success: bool
    output: str = ""
    agent_id: str = ""
    routing_scores: dict[str, float] | None = None
    tokens_used: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    stage_failed: str = ""  # "routing" | "dispatch" | ""

    @property
    def failed(self) -> bool:
        return not self.success


class Pipeline:
    """Minimal end-to-end integration harness.

    Owns the registry stack and dispatcher. Provides a single `run()`
    method that goes from task description to execution result.
    """

    def __init__(
        self,
        dispatcher_config: DispatcherConfig | None = None,
        router_config: RouterConfig | None = None,
        api_client: Any = None,
    ) -> None:
        self.vocabulary = CapabilityVocabulary()
        self.validator = SchemaValidator(self.vocabulary)
        self.registry = AgentRegistry(self.validator, self.vocabulary)
        self.trust = TrustRegistry()
        self._router_config = router_config or RouterConfig(
            minimum_confidence_threshold=-1000.0  # Harness is permissive; governor enforces thresholds
        )
        self._dispatcher = Dispatcher(
            registry=self.registry,
            config=dispatcher_config,
            api_client=api_client,
        )

    def register_agent(self, spec: AgentSpec) -> RegistrationResult:
        """Register an agent spec. Returns registration result."""
        return self.registry.register(spec)

    def set_trust(
        self,
        agent_id: str,
        tier: TrustTier,
        granted_by: str,
        notes: str = "",
    ) -> None:
        """Set trust tier for an agent."""
        self.trust.set_trust(agent_id, tier, granted_by, notes=notes)

    def add_capability(self, capability: str) -> None:
        """Register a new capability tag in the vocabulary."""
        self.vocabulary.register_capability(capability)

    def run(
        self,
        task_id: str,
        required_capabilities: list[str],
        inputs_available: list[str],
        prompt: str,
        *,
        preferred_capabilities: list[str] | None = None,
        risk_tier: RiskTier = RiskTier.LOW,
        routing_mode: RoutingMode = RoutingMode.SINGLE,
        task_context: dict[str, Any] | None = None,
    ) -> PipelineResult:
        """Run full pipeline: route → dispatch → result.

        Args:
            task_id: Unique task identifier.
            required_capabilities: What the task needs.
            inputs_available: What data is available.
            prompt: The actual instruction for the agent.
            preferred_capabilities: Nice-to-have capabilities for scoring.
            risk_tier: Task risk level for admission control.
            routing_mode: How to select candidates.
            task_context: Optional structured context dict.

        Returns:
            PipelineResult with output or structured error.
        """
        # --- Build task descriptor ---
        try:
            task = TaskDescriptor.create(
                task_id=task_id,
                required_capabilities=required_capabilities,
                inputs_available=inputs_available,
                preferred_capabilities=preferred_capabilities or [],
                risk_tier=risk_tier,
                routing_mode=routing_mode,
            )
        except ValueError as e:
            return PipelineResult(
                task_id=task_id,
                success=False,
                error=str(e),
                stage_failed="routing",
            )

        # --- Route ---
        route_outcome = route(
            task,
            self.registry,
            self.trust,
            config=self._router_config,
        )

        if isinstance(route_outcome, RoutingFailure):
            return PipelineResult(
                task_id=task_id,
                success=False,
                error=f"Routing failed: {route_outcome.reason.value} — {route_outcome.detail}",
                stage_failed="routing",
            )

        # Collect scores for observability
        scores = {
            c.agent_id: c.score
            for c in route_outcome.all_candidates
        }

        # --- Dispatch ---
        exec_result = self._dispatcher.dispatch(
            route_result=route_outcome,
            task_prompt=prompt,
            task_context=task_context,
        )

        if exec_result.success:
            return PipelineResult(
                task_id=task_id,
                success=True,
                output=exec_result.output,
                agent_id=exec_result.agent_id,
                routing_scores=scores,
                tokens_used=exec_result.tokens_used,
                duration_seconds=exec_result.duration_seconds,
            )
        else:
            return PipelineResult(
                task_id=task_id,
                success=False,
                agent_id=exec_result.agent_id,
                error=exec_result.error,
                routing_scores=scores,
                duration_seconds=exec_result.duration_seconds,
                stage_failed="dispatch",
            )

    def dry_run(
        self,
        task_id: str,
        required_capabilities: list[str],
        inputs_available: list[str],
        *,
        preferred_capabilities: list[str] | None = None,
        risk_tier: RiskTier = RiskTier.LOW,
    ) -> RouteResult | RoutingFailure:
        """Route only — no dispatch. For testing routing decisions."""
        task = TaskDescriptor.create(
            task_id=task_id,
            required_capabilities=required_capabilities,
            inputs_available=inputs_available,
            preferred_capabilities=preferred_capabilities or [],
            risk_tier=risk_tier,
        )
        return route(task, self.registry, self.trust, config=self._router_config)
