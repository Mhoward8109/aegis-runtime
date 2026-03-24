"""Chain — Minimal Sequential Orchestration.

The simplest useful multi-step pattern:
  step A runs → its output feeds step B → step B runs → done.

This is NOT the full orchestration grammar from the contracts.
It is the first concrete multi-agent behavior, built because the
burn-in showed the pattern: review code → write tests.

What a Chain does:
  - Runs steps in sequence
  - Each step's output is available to subsequent steps via {{prev.output}}
  - If any step fails, the chain stops with a structured result
  - All steps emit events through the state authority
  - The chain itself is a thin coordinator, not a state machine

What a Chain does NOT do:
  - Fork/join
  - Conditional branching
  - Parallel execution
  - Retry logic (individual steps can fail; chain stops)
  - Budget tracking
  - Rollback

Those come later, when real usage demands them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from aegis.models.enums import RiskTier, RoutingMode
from aegis.harness.pipeline import Pipeline, PipelineResult


@dataclass(frozen=True)
class ChainStep:
    """A single step in a chain.

    The prompt can reference previous step outputs using:
      {{prev.output}}      — full output of the immediately preceding step
      {{steps.STEP_ID.output}} — output of a specific earlier step
      {{context.KEY}}      — value from the chain's shared context
    """
    step_id: str
    required_capabilities: list[str]
    inputs_available: list[str]
    prompt_template: str
    preferred_capabilities: list[str] = field(default_factory=list)
    risk_tier: RiskTier = RiskTier.LOW


@dataclass
class ChainStepResult:
    """Result of a single chain step."""
    step_id: str
    success: bool
    agent_id: str = ""
    output: str = ""
    tokens_used: int = 0
    duration_seconds: float = 0.0
    error: str = ""


@dataclass
class ChainResult:
    """Result of running a full chain."""
    chain_id: str
    success: bool
    steps_completed: int
    steps_total: int
    step_results: list[ChainStepResult] = field(default_factory=list)
    total_tokens: int = 0
    total_duration: float = 0.0
    final_output: str = ""
    failed_step: str = ""
    error: str = ""

    @property
    def all_outputs(self) -> dict[str, str]:
        """Map of step_id → output for all completed steps."""
        return {r.step_id: r.output for r in self.step_results if r.success}


def run_chain(
    pipeline: Pipeline,
    chain_id: str,
    steps: list[ChainStep],
    context: dict[str, str] | None = None,
) -> ChainResult:
    """Run a sequential chain of steps through the pipeline.

    Each step's prompt template is resolved with:
      {{prev.output}} — output from the previous step
      {{steps.STEP_ID.output}} — output from a named earlier step
      {{context.KEY}} — value from the context dict

    Args:
        pipeline: The wired pipeline (registry + router + dispatcher + state).
        chain_id: Unique identifier for this chain run.
        steps: Ordered list of steps to execute.
        context: Optional shared context available to all steps.

    Returns:
        ChainResult with all step results and final output.
    """
    if not steps:
        return ChainResult(
            chain_id=chain_id, success=False,
            steps_completed=0, steps_total=0,
            error="Empty chain — no steps to run",
        )

    ctx = dict(context or {})
    step_outputs: dict[str, str] = {}
    step_results: list[ChainStepResult] = []
    prev_output = ""
    total_tokens = 0
    chain_start = time.monotonic()

    for i, step in enumerate(steps):
        # Resolve prompt template
        prompt = _resolve_template(step.prompt_template, prev_output, step_outputs, ctx)

        # Run through pipeline
        task_id = f"{chain_id}.{step.step_id}"
        result = pipeline.run(
            task_id=task_id,
            required_capabilities=step.required_capabilities,
            inputs_available=step.inputs_available,
            preferred_capabilities=step.preferred_capabilities,
            risk_tier=step.risk_tier,
            prompt=prompt,
        )

        step_result = ChainStepResult(
            step_id=step.step_id,
            success=result.success,
            agent_id=result.agent_id,
            output=result.output,
            tokens_used=result.tokens_used,
            duration_seconds=result.duration_seconds,
            error=result.error,
        )
        step_results.append(step_result)

        if result.success:
            prev_output = result.output
            step_outputs[step.step_id] = result.output
            total_tokens += result.tokens_used
        else:
            # Chain stops on first failure
            total_duration = time.monotonic() - chain_start
            return ChainResult(
                chain_id=chain_id,
                success=False,
                steps_completed=i,
                steps_total=len(steps),
                step_results=step_results,
                total_tokens=total_tokens,
                total_duration=round(total_duration, 3),
                failed_step=step.step_id,
                error=f"Step '{step.step_id}' failed: {result.error}",
            )

    total_duration = time.monotonic() - chain_start
    return ChainResult(
        chain_id=chain_id,
        success=True,
        steps_completed=len(steps),
        steps_total=len(steps),
        step_results=step_results,
        total_tokens=total_tokens,
        total_duration=round(total_duration, 3),
        final_output=prev_output,
    )


def _resolve_template(
    template: str,
    prev_output: str,
    step_outputs: dict[str, str],
    context: dict[str, str],
) -> str:
    """Resolve {{...}} placeholders in a prompt template."""
    result = template

    # {{prev.output}}
    result = result.replace("{{prev.output}}", prev_output)

    # {{steps.STEP_ID.output}}
    for step_id, output in step_outputs.items():
        result = result.replace(f"{{{{steps.{step_id}.output}}}}", output)

    # {{context.KEY}}
    for key, value in context.items():
        result = result.replace(f"{{{{context.{key}}}}}", value)

    return result
