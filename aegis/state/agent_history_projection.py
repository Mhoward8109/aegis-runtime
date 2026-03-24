"""Agent Execution History Projection — State Authority P1b.

Derives agent performance metrics from event replay. Answers:
  - How many tasks has this agent run?
  - How many completed vs failed?
  - Basic latency stats
  - Recent failure recency

Implements the ExperienceStore protocol from P1 scoring,
so the router can consume it WITHOUT adapter code.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from aegis.state.event import Event, EventType, EventScope


@dataclass
class AgentRecord:
    """Execution record for a single task run by an agent."""
    task_id: str
    completed: bool
    tokens_used: int = 0
    duration_seconds: float = 0.0
    task_type: str = ""  # first required capability, used as task type proxy


@dataclass
class AgentHistory:
    """Accumulated history for a single agent."""
    agent_id: str
    records: list[AgentRecord] = field(default_factory=list)

    @property
    def total_tasks(self) -> int:
        return len(self.records)

    @property
    def completed_tasks(self) -> int:
        return sum(1 for r in self.records if r.completed)

    @property
    def failed_tasks(self) -> int:
        return sum(1 for r in self.records if not r.completed)

    @property
    def overall_success_rate(self) -> float | None:
        if not self.records:
            return None
        return self.completed_tasks / self.total_tasks

    def success_rate_for_type(self, task_type: str) -> float | None:
        typed = [r for r in self.records if r.task_type == task_type]
        if not typed:
            return None
        return sum(1 for r in typed if r.completed) / len(typed)

    def average_latency_for_type(self, task_type: str) -> float | None:
        typed = [r for r in self.records if r.task_type == task_type and r.completed]
        if not typed:
            return None
        return statistics.mean(r.duration_seconds for r in typed)

    def recent_failure(self, task_type: str, last_n: int = 3) -> bool:
        typed = [r for r in self.records if r.task_type == task_type]
        recent = typed[-last_n:] if len(typed) >= last_n else typed
        return any(not r.completed for r in recent)


class AgentExecutionHistoryProjection:
    """Projects agent execution metrics from event streams.

    Implements the ExperienceStore protocol so the router
    can consume it directly — no adapter needed.

    Protocol methods:
      success_rate(agent_id, task_type) → float | None
      average_latency(agent_id, task_type) → float | None
      median_latency(task_type) → float | None
      recent_failure(agent_id, task_type, last_n) → bool
      flagged_for_overruns(agent_id) → bool
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentHistory] = {}
        # Track in-flight tasks: task_id → (agent_id, task_type)
        self._in_flight: dict[str, tuple[str, str]] = {}

    def apply(self, event: Event) -> None:
        """Apply a single event to update agent history.

        Tracks task.created (for task_type), task.started (for in-flight),
        task.completed and task.failed (for records).
        """
        match event.event_type:
            case EventType.TASK_CREATED:
                # Extract task_type as first required capability
                caps = event.payload.get("required_capabilities", [])
                task_type = caps[0] if caps else ""
                # Store for later lookup when task completes
                self._in_flight[event.task_id] = ("", task_type)

            case EventType.TASK_STARTED:
                agent_id = event.payload.get("agent_id", event.agent_id)
                existing = self._in_flight.get(event.task_id, ("", ""))
                self._in_flight[event.task_id] = (agent_id, existing[1])

            case EventType.TASK_COMPLETED:
                agent_id = event.payload.get("agent_id", event.agent_id)
                in_flight = self._in_flight.pop(event.task_id, None)
                task_type = in_flight[1] if in_flight else ""

                self._ensure_agent(agent_id)
                self._agents[agent_id].records.append(AgentRecord(
                    task_id=event.task_id,
                    completed=True,
                    tokens_used=event.payload.get("tokens_used", 0),
                    duration_seconds=event.payload.get("duration_seconds", 0.0),
                    task_type=task_type,
                ))

            case EventType.TASK_FAILED:
                agent_id = event.payload.get("agent_id", event.agent_id)
                in_flight = self._in_flight.pop(event.task_id, None)
                task_type = in_flight[1] if in_flight else ""

                # Only record agent-level failures (not routing failures)
                if agent_id:
                    self._ensure_agent(agent_id)
                    self._agents[agent_id].records.append(AgentRecord(
                        task_id=event.task_id,
                        completed=False,
                        task_type=task_type,
                    ))

    # --- ExperienceStore protocol implementation ---

    def success_rate(self, agent_id: str, task_type: str) -> float | None:
        """Return success rate [0.0, 1.0] or None if no data."""
        history = self._agents.get(agent_id)
        if not history:
            return None
        return history.success_rate_for_type(task_type)

    def average_latency(self, agent_id: str, task_type: str) -> float | None:
        """Return average latency in seconds or None if no data."""
        history = self._agents.get(agent_id)
        if not history:
            return None
        return history.average_latency_for_type(task_type)

    def median_latency(self, task_type: str) -> float | None:
        """Return median latency across all agents for this task type."""
        all_latencies: list[float] = []
        for history in self._agents.values():
            for record in history.records:
                if record.task_type == task_type and record.completed:
                    all_latencies.append(record.duration_seconds)
        if not all_latencies:
            return None
        return statistics.median(all_latencies)

    def recent_failure(self, agent_id: str, task_type: str, last_n: int = 3) -> bool:
        """Return True if agent failed this task type in last N runs."""
        history = self._agents.get(agent_id)
        if not history:
            return False
        return history.recent_failure(task_type, last_n)

    def flagged_for_overruns(self, agent_id: str) -> bool:
        """Return True if agent has been flagged for budget overruns.
        
        Not yet implemented — requires budget tracking (deferred).
        Always returns False at P1b.
        """
        return False

    # --- Query methods ---

    def get_history(self, agent_id: str) -> AgentHistory | None:
        """Get full history for an agent."""
        return self._agents.get(agent_id)

    def list_agents(self) -> list[str]:
        """All agents with execution history."""
        return list(self._agents.keys())

    def clear(self) -> None:
        """Clear all cached history. Used before full replay."""
        self._agents.clear()
        self._in_flight.clear()

    def _ensure_agent(self, agent_id: str) -> None:
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentHistory(agent_id=agent_id)
