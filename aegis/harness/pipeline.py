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
from aegis.state.state_authority import StateAuthority
from aegis.state import event as evt

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

    Owns the registry stack, dispatcher, and state authority.
    Emits events at each lifecycle stage. Provides a single `run()`
    method that goes from task description to execution result.
    """

    def __init__(
        self,
        dispatcher_config: DispatcherConfig | None = None,
        router_config: RouterConfig | None = None,
        api_client: Any = None,
        state: StateAuthority | None = None,
    ) -> None:
        self.vocabulary = CapabilityVocabulary()
        self.validator = SchemaValidator(self.vocabulary)
        self.registry = AgentRegistry(self.validator, self.vocabulary)
        self.trust = TrustRegistry()
        self.state = state or StateAuthority()
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

        Emits events to StateAuthority at each lifecycle stage.
        Passes agent execution history to router for scoring.
        """
        # --- Emit task.created ---
        self.state.record(evt.task_created(
            task_id=task_id,
            required_capabilities=required_capabilities,
            inputs_available=inputs_available,
            preferred_capabilities=preferred_capabilities,
            risk_tier=risk_tier.value if isinstance(risk_tier, RiskTier) else str(risk_tier),
            routing_mode=routing_mode.value if isinstance(routing_mode, RoutingMode) else str(routing_mode),
        ))

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
            self.state.record(evt.task_failed(
                task_id=task_id, stage_failed="routing", error=str(e),
            ))
            return PipelineResult(
                task_id=task_id,
                success=False,
                error=str(e),
                stage_failed="routing",
            )

        # --- Route (with experience store for scoring) ---
        route_outcome = route(
            task,
            self.registry,
            self.trust,
            config=self._router_config,
            experience_store=self.state.experience_store,
        )

        if isinstance(route_outcome, RoutingFailure):
            self.state.record(evt.task_failed(
                task_id=task_id,
                stage_failed="routing",
                error=f"{route_outcome.reason.value}: {route_outcome.detail}",
            ))
            return PipelineResult(
                task_id=task_id,
                success=False,
                error=f"Routing failed: {route_outcome.reason.value} — {route_outcome.detail}",
                stage_failed="routing",
            )

        # --- Emit task.routed ---
        self.state.record(evt.task_routed(
            task_id=task_id,
            primary_agent_id=route_outcome.primary.agent_id,
            primary_score=route_outcome.primary.score,
            fallback_agent_ids=[f.agent_id for f in route_outcome.fallbacks],
            candidates_evaluated=route_outcome.candidates_evaluated,
            candidates_filtered=route_outcome.candidates_filtered,
            reasoning=[
                {"factor": r.factor, "delta": r.delta, "detail": r.detail}
                for r in route_outcome.primary.reasons
            ],
        ))

        # Collect scores for observability
        scores = {
            c.agent_id: c.score
            for c in route_outcome.all_candidates
        }

        # --- Emit task.started ---
        self.state.record(evt.task_started(
            task_id=task_id,
            agent_id=route_outcome.primary.agent_id,
            model=self._dispatcher._config.model,
        ))

        # --- Dispatch ---
        exec_result = self._dispatcher.dispatch(
            route_result=route_outcome,
            task_prompt=prompt,
            task_context=task_context,
        )

        if exec_result.success:
            # --- Emit agent.output + task.completed ---
            self.state.record(evt.agent_output(
                task_id=task_id,
                agent_id=exec_result.agent_id,
                output=exec_result.output,
            ))
            self.state.record(evt.task_completed(
                task_id=task_id,
                agent_id=exec_result.agent_id,
                tokens_used=exec_result.tokens_used,
                duration_seconds=exec_result.duration_seconds,
                output_length=len(exec_result.output),
            ))
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
            # --- Emit task.failed ---
            self.state.record(evt.task_failed(
                task_id=task_id,
                stage_failed="dispatch",
                error=exec_result.error,
                agent_id=exec_result.agent_id,
            ))
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
        """Route only — no dispatch, no events. For testing routing decisions."""
        task = TaskDescriptor.create(
            task_id=task_id,
            required_capabilities=required_capabilities,
            inputs_available=inputs_available,
            preferred_capabilities=preferred_capabilities or [],
            risk_tier=risk_tier,
        )
        return route(
            task, self.registry, self.trust,
            config=self._router_config,
            experience_store=self.state.experience_store,
        )
