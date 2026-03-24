"""Scoring — Contract 2 §2.3 step 2.

Pure scoring functions. No side effects. No registry access.
These functions take pre-filtered candidates and task descriptors
and return scored results.

Scoring components:
  a. capability_match: preferred match + specialization bonus
  b. context_relevance: stub (requires experience store, P3)
  c. historical_performance: stub (requires experience store, P3)
  d. cost_risk: budget proximity penalty + overrun flag

Stubs return 0.0 and accept protocol-compatible interfaces so they
can be replaced without changing the router's calling code.
"""

from __future__ import annotations

from typing import Protocol

from aegis.models.agent_spec import AgentSpec
from aegis.router.task_descriptor import TaskDescriptor
from aegis.router.types import RoutingReason


# ---------------------------------------------------------------------------
# Protocols for future store integration (P3)
# ---------------------------------------------------------------------------


class ExperienceStore(Protocol):
    """Interface for historical performance data.

    Stubbed at P1. Implemented at P3 when the completion reconciler
    starts recording metrics.
    """

    def success_rate(self, agent_id: str, task_type: str) -> float | None:
        """Return success rate [0.0, 1.0] or None if no data."""
        ...

    def average_latency(self, agent_id: str, task_type: str) -> float | None:
        """Return average latency in seconds or None if no data."""
        ...

    def median_latency(self, task_type: str) -> float | None:
        """Return median latency across all agents for this task type."""
        ...

    def recent_failure(self, agent_id: str, task_type: str, last_n: int) -> bool:
        """Return True if agent failed this task type in last N runs."""
        ...

    def flagged_for_overruns(self, agent_id: str) -> bool:
        """Return True if agent has been flagged for budget overruns."""
        ...


class ContextStore(Protocol):
    """Interface for workflow context data.

    Stubbed at P1. Implemented when state authority is live.
    """

    def recently_succeeded(self, agent_id: str, task_type: str) -> bool:
        """True if agent recently succeeded on similar task type."""
        ...

    def has_warm_context(self, agent_id: str, workflow_id: str) -> bool:
        """True if agent has warm context from current workflow."""
        ...


# ---------------------------------------------------------------------------
# Null implementations (active at P1)
# ---------------------------------------------------------------------------


class NullExperienceStore:
    """Returns no data for all queries. Active until P3."""

    def success_rate(self, agent_id: str, task_type: str) -> float | None:
        return None

    def average_latency(self, agent_id: str, task_type: str) -> float | None:
        return None

    def median_latency(self, task_type: str) -> float | None:
        return None

    def recent_failure(self, agent_id: str, task_type: str, last_n: int) -> bool:
        return False

    def flagged_for_overruns(self, agent_id: str) -> bool:
        return False


class NullContextStore:
    """Returns no context for all queries. Active until state authority is live."""

    def recently_succeeded(self, agent_id: str, task_type: str) -> bool:
        return False

    def has_warm_context(self, agent_id: str, workflow_id: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Scoring functions — pure, no side effects
# ---------------------------------------------------------------------------


def score_capability_match(
    task: TaskDescriptor,
    agent: AgentSpec,
) -> list[RoutingReason]:
    """Score preferred capability match and specialization.

    Contract 2 §2.3 step 2a:
    - preferred match:   +25 per matched preferred capability
    - specialization:    +15 if agent capability overlap ratio > 0.7
    """
    reasons: list[RoutingReason] = []

    # Preferred capability match
    if task.preferred_capabilities:
        matched = set(task.preferred_capabilities) & set(agent.capabilities)
        if matched:
            delta = len(matched) * 25.0
            reasons.append(RoutingReason(
                factor="preferred_capability",
                delta=delta,
                detail=f"Matched preferred: {sorted(matched)}",
            ))

    # Specialization bonus
    if agent.capabilities:
        task_caps = set(task.required_capabilities) | set(task.preferred_capabilities)
        overlap = len(set(agent.capabilities) & task_caps) / len(agent.capabilities)
        if overlap > 0.7:
            reasons.append(RoutingReason(
                factor="specialization",
                delta=15.0,
                detail=f"Overlap ratio {overlap:.2f} > 0.7",
            ))

    return reasons


def score_context_relevance(
    task: TaskDescriptor,
    agent: AgentSpec,
    context_store: ContextStore,
    workflow_id: str | None = None,
) -> list[RoutingReason]:
    """Score context relevance.

    Contract 2 §2.3 step 2b:
    - recently succeeded on similar task type: +30
    - warm context from current workflow:      +20
    - cold:                                    +0

    Stubbed at P1 via NullContextStore. Returns empty list.
    Interface is stable — P2/P3 implementation drops in without router changes.
    """
    reasons: list[RoutingReason] = []

    task_type = task.required_capabilities[0] if task.required_capabilities else ""

    if context_store.recently_succeeded(agent.agent_id, task_type):
        reasons.append(RoutingReason(
            factor="context_recent_success",
            delta=30.0,
            detail=f"Recently succeeded on {task_type}",
        ))

    if workflow_id and context_store.has_warm_context(agent.agent_id, workflow_id):
        reasons.append(RoutingReason(
            factor="context_warm",
            delta=20.0,
            detail=f"Warm context from workflow {workflow_id}",
        ))

    return reasons


def score_historical_performance(
    task: TaskDescriptor,
    agent: AgentSpec,
    experience_store: ExperienceStore,
) -> list[RoutingReason]:
    """Score historical performance.

    Contract 2 §2.3 step 2c:
    - success_rate:    weight * success_rate (weight = 40)
    - latency penalty: -1 per second above median
    - failure_recency: -50 if failed same task type in last 3 runs

    Stubbed at P1 via NullExperienceStore. Returns empty list.
    Interface is stable — P3 implementation drops in without router changes.
    """
    reasons: list[RoutingReason] = []

    task_type = task.required_capabilities[0] if task.required_capabilities else ""

    # Success rate
    success = experience_store.success_rate(agent.agent_id, task_type)
    if success is not None:
        delta = 40.0 * success
        reasons.append(RoutingReason(
            factor="historical_success_rate",
            delta=delta,
            detail=f"Success rate {success:.2f} for {task_type}",
        ))

    # Latency penalty
    avg_latency = experience_store.average_latency(agent.agent_id, task_type)
    median_latency = experience_store.median_latency(task_type)
    if avg_latency is not None and median_latency is not None:
        excess = avg_latency - median_latency
        if excess > 0:
            reasons.append(RoutingReason(
                factor="latency_penalty",
                delta=-excess,
                detail=f"Avg latency {avg_latency:.1f}s vs median {median_latency:.1f}s",
            ))

    # Failure recency
    if experience_store.recent_failure(agent.agent_id, task_type, last_n=3):
        reasons.append(RoutingReason(
            factor="failure_recency",
            delta=-50.0,
            detail=f"Failed {task_type} in last 3 runs",
        ))

    return reasons


def score_cost_risk(
    task: TaskDescriptor,
    agent: AgentSpec,
    experience_store: ExperienceStore,
) -> list[RoutingReason]:
    """Score cost risk.

    Contract 2 §2.3 step 2d:
    - cost_time_ratio:  DISABLED — burn-in proved it's uniform noise
                        (every agent gets -20 with default configs)
                        Re-enable when real per-agent cost data exists.
    - flagged for budget overruns: -30 (active, from experience store)
    """
    reasons: list[RoutingReason] = []

    # cost_time_ratio: DISABLED per burn-in finding #3.
    # When all agents share default timeouts, this penalizes everyone
    # equally and discriminates nothing. Re-enable when agents have
    # differentiated cost profiles or real cost data is available.

    # Budget overrun flag (still active — discriminates when data exists)
    if experience_store.flagged_for_overruns(agent.agent_id):
        reasons.append(RoutingReason(
            factor="cost_overrun_flag",
            delta=-30.0,
            detail="Agent flagged for budget overruns",
        ))

    return reasons


def score_exploration_bonus(
    task: TaskDescriptor,
    agent: AgentSpec,
    experience_store: ExperienceStore,
    low_history_threshold: int = 3,
    bonus: float = 10.0,
) -> list[RoutingReason]:
    """Mild exploration bonus for low-history agents.

    Burn-in finding: rich-get-richer effect means agents that win early
    keep winning because they accumulate history faster. This bonus
    gives underused but eligible agents a small boost to prevent
    complete starvation.

    Policy: controlled exploration, not pure exploitation.
    - Agents with < low_history_threshold completions for this task type
      get a small bonus.
    - The bonus is intentionally smaller than the historical success rate
      weight (40) so proven agents still win — but new agents get a chance.
    """
    reasons: list[RoutingReason] = []

    task_type = task.required_capabilities[0] if task.required_capabilities else ""
    success_rate = experience_store.success_rate(agent.agent_id, task_type)

    if success_rate is None:
        # No history at all — agent has never run this task type
        reasons.append(RoutingReason(
            factor="exploration_no_history",
            delta=bonus,
            detail=f"No history for {task_type} — exploration bonus",
        ))
    else:
        # Check if history is thin
        history = getattr(experience_store, 'get_history', lambda x: None)(agent.agent_id)
        if history:
            typed_count = sum(
                1 for r in history.records if r.task_type == task_type
            )
            if typed_count < low_history_threshold:
                reduced_bonus = bonus * 0.5  # Half bonus for thin history
                reasons.append(RoutingReason(
                    factor="exploration_low_history",
                    delta=reduced_bonus,
                    detail=f"Only {typed_count} runs for {task_type} — exploration bonus",
                ))

    return reasons


def compute_total_score(reasons: list[RoutingReason]) -> float:
    """Sum all scoring deltas."""
    return sum(r.delta for r in reasons)
