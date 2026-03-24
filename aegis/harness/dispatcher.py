"""Dispatcher — Minimal Integration Harness.

Takes a RouteResult from the router and dispatches the selected agent
to the Claude API. Returns a structured ExecutionResult.

This is NOT an orchestrator. It does NOT:
- Fork/join
- Emit events
- Manage workflow state
- Retry beyond consuming fallback candidates
- Reserve or track budgets

It DOES:
- Build a prompt from the agent spec + task
- Call the Claude API
- Return structured output
- Fall back to next candidate on API failure
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from aegis.models.agent_spec import AgentSpec
from aegis.models.enums import AgentStatus
from aegis.registry.agent_registry import AgentRegistry
from aegis.router.types import RouteResult, RoutingFailure, ScoredCandidate


@dataclass(frozen=True)
class ExecutionResult:
    """Output from a single agent dispatch."""
    task_id: str
    agent_id: str
    success: bool
    output: str
    model: str = ""
    tokens_used: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    fallback_attempts: int = 0

    @property
    def failed(self) -> bool:
        return not self.success


@dataclass
class DispatcherConfig:
    """Configuration for the dispatcher."""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.0
    max_fallback_attempts: int = 3
    timeout_seconds: float = 120.0


class Dispatcher:
    """Thin dispatch layer: RouteResult → Claude API → ExecutionResult.

    Requires an Anthropic API client. Does not manage its own HTTP.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        config: DispatcherConfig | None = None,
        api_client: Any = None,
    ) -> None:
        """Initialize dispatcher.

        Args:
            registry: Agent registry for looking up full specs.
            config: Dispatch configuration.
            api_client: An anthropic.Anthropic client instance.
                If None, will attempt to import and create one.
        """
        self._registry = registry
        self._config = config or DispatcherConfig()
        self._client = api_client

    def _get_client(self) -> Any:
        """Lazy-initialize the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except ImportError:
                raise RuntimeError(
                    "anthropic package not installed. "
                    "Run: pip install anthropic"
                )
        return self._client

    def dispatch(
        self,
        route_result: RouteResult,
        task_prompt: str,
        task_context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Dispatch a routed task to the Claude API.

        Tries the primary candidate first, then falls back through
        ranked alternatives on failure.

        Args:
            route_result: Successful routing result with primary + fallbacks.
            task_prompt: The actual task/instruction to send to the agent.
            task_context: Optional structured context to include in the prompt.

        Returns:
            ExecutionResult with agent output or error details.
        """
        candidates = [route_result.primary] + list(route_result.fallbacks)
        candidates = candidates[:self._config.max_fallback_attempts + 1]

        last_error = ""
        for attempt, candidate in enumerate(candidates):
            spec = self._registry.get(candidate.agent_id)
            if spec is None:
                last_error = f"Agent {candidate.agent_id} not found in registry"
                continue

            result = self._execute_single(
                task_id=route_result.task_id,
                spec=spec,
                task_prompt=task_prompt,
                task_context=task_context,
                fallback_attempts=attempt,
            )

            if result.success:
                return result

            last_error = result.error

        # All candidates failed
        return ExecutionResult(
            task_id=route_result.task_id,
            agent_id=candidates[-1].agent_id if candidates else "none",
            success=False,
            output="",
            error=f"All {len(candidates)} candidates failed. Last error: {last_error}",
            fallback_attempts=len(candidates) - 1,
        )

    def _execute_single(
        self,
        task_id: str,
        spec: AgentSpec,
        task_prompt: str,
        task_context: dict[str, Any] | None,
        fallback_attempts: int,
    ) -> ExecutionResult:
        """Execute a single agent against the Claude API."""
        system_prompt = self._build_system_prompt(spec)
        user_message = self._build_user_message(task_prompt, task_context)

        start = time.monotonic()
        try:
            client = self._get_client()
            response = client.messages.create(
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            duration = time.monotonic() - start

            # Extract text from response
            output_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    output_text += block.text

            tokens = (
                response.usage.input_tokens + response.usage.output_tokens
                if response.usage
                else 0
            )

            return ExecutionResult(
                task_id=task_id,
                agent_id=spec.agent_id,
                success=True,
                output=output_text,
                model=self._config.model,
                tokens_used=tokens,
                duration_seconds=round(duration, 3),
                fallback_attempts=fallback_attempts,
            )

        except Exception as e:
            duration = time.monotonic() - start
            return ExecutionResult(
                task_id=task_id,
                agent_id=spec.agent_id,
                success=False,
                output="",
                error=f"{type(e).__name__}: {e}",
                duration_seconds=round(duration, 3),
                fallback_attempts=fallback_attempts,
            )

    def _build_system_prompt(self, spec: AgentSpec) -> str:
        """Build system prompt from agent spec."""
        lines = [
            f"You are {spec.role} (agent: {spec.agent_id}).",
            "",
            "## Capabilities",
            ", ".join(spec.capabilities),
            "",
        ]

        if spec.constraints:
            lines.extend([
                "## Constraints",
                "You MUST follow these rules:",
            ])
            for c in spec.constraints:
                lines.append(f"- {c}")
            lines.append("")

        if spec.tools:
            lines.extend([
                "## Available Tools",
                ", ".join(spec.tools),
                "",
            ])

        lines.extend([
            "## Output Requirements",
            f"You produce: {', '.join(spec.outputs)}",
            "",
            "Be precise, complete, and follow all constraints.",
        ])

        return "\n".join(lines)

    def _build_user_message(
        self,
        task_prompt: str,
        task_context: dict[str, Any] | None,
    ) -> str:
        """Build user message with optional structured context."""
        if not task_context:
            return task_prompt

        context_str = json.dumps(task_context, indent=2, default=str)
        return f"## Context\n```json\n{context_str}\n```\n\n## Task\n{task_prompt}"
