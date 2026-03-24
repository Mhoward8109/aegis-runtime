"""Task Lifecycle Projection — State Authority P1b.

Derives current task state from event replay. Answers:
  - What state is the task in?
  - Which agent was selected?
  - What output exists?
  - When did it fail or complete?
  - What was the routing decision?

Lifecycle: created → routed → started → completed/failed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aegis.state.event import Event, EventType


@dataclass
class TaskState:
    """Current state of a single task, derived from events."""
    task_id: str
    status: str = "unknown"  # created | routed | started | completed | failed
    agent_id: str = ""
    
    # From task.created
    required_capabilities: list[str] = field(default_factory=list)
    inputs_available: list[str] = field(default_factory=list)
    risk_tier: str = ""
    
    # From task.routed
    primary_agent_id: str = ""
    primary_score: float = 0.0
    fallback_agent_ids: list[str] = field(default_factory=list)
    candidates_evaluated: int = 0
    candidates_filtered: int = 0
    routing_reasoning: list[dict[str, Any]] = field(default_factory=list)
    
    # From task.started
    model: str = ""
    started_at: str = ""
    
    # From task.completed
    tokens_used: int = 0
    duration_seconds: float = 0.0
    output_length: int = 0
    completed_at: str = ""
    
    # From task.failed
    stage_failed: str = ""
    error: str = ""
    failed_at: str = ""
    
    # From agent.output
    output: str = ""
    
    # Metadata
    created_at: str = ""
    event_count: int = 0


class TaskLifecycleProjection:
    """Projects task state from event streams.

    Maintains an in-memory cache of task states. Can rebuild
    any task state from scratch by replaying its events.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskState] = {}

    def apply(self, event: Event) -> TaskState:
        """Apply a single event and return updated task state.

        Called by the event log consumer (harness or orchestrator)
        after each event is appended.
        """
        task_id = event.task_id
        if task_id not in self._tasks:
            self._tasks[task_id] = TaskState(task_id=task_id)

        state = self._tasks[task_id]
        state.event_count += 1

        match event.event_type:
            case EventType.TASK_CREATED:
                state.status = "created"
                state.created_at = event.timestamp
                state.required_capabilities = event.payload.get("required_capabilities", [])
                state.inputs_available = event.payload.get("inputs_available", [])
                state.risk_tier = event.payload.get("risk_tier", "")

            case EventType.TASK_ROUTED:
                state.status = "routed"
                state.primary_agent_id = event.payload.get("primary_agent_id", "")
                state.primary_score = event.payload.get("primary_score", 0.0)
                state.fallback_agent_ids = event.payload.get("fallback_agent_ids", [])
                state.candidates_evaluated = event.payload.get("candidates_evaluated", 0)
                state.candidates_filtered = event.payload.get("candidates_filtered", 0)
                state.routing_reasoning = event.payload.get("reasoning", [])
                state.agent_id = state.primary_agent_id

            case EventType.TASK_STARTED:
                state.status = "started"
                state.agent_id = event.payload.get("agent_id", "")
                state.model = event.payload.get("model", "")
                state.started_at = event.timestamp

            case EventType.TASK_COMPLETED:
                state.status = "completed"
                state.tokens_used = event.payload.get("tokens_used", 0)
                state.duration_seconds = event.payload.get("duration_seconds", 0.0)
                state.output_length = event.payload.get("output_length", 0)
                state.completed_at = event.timestamp

            case EventType.TASK_FAILED:
                state.status = "failed"
                state.stage_failed = event.payload.get("stage_failed", "")
                state.error = event.payload.get("error", "")
                state.failed_at = event.timestamp

            case EventType.AGENT_OUTPUT:
                state.output = event.payload.get("output", "")

        return state

    def get(self, task_id: str) -> TaskState | None:
        """Get current state of a task. Returns None if unknown."""
        return self._tasks.get(task_id)

    def list_tasks(self, status: str | None = None) -> list[TaskState]:
        """List all tracked tasks, optionally filtered by status."""
        if status:
            return [t for t in self._tasks.values() if t.status == status]
        return list(self._tasks.values())

    def rebuild(self, events: list[Event]) -> TaskState | None:
        """Rebuild task state from a complete event stream.

        Used for replay/verification. Creates a fresh state
        and applies all events in order.
        """
        if not events:
            return None

        task_id = events[0].task_id

        # Clear existing state for this task
        self._tasks.pop(task_id, None)

        state = None
        for event in events:
            state = self.apply(event)

        return state

    def clear(self) -> None:
        """Clear all cached state. Used before full replay."""
        self._tasks.clear()
