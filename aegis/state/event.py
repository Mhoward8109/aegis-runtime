"""Event Model — State Authority P1b.

6 canonical event types, derived from trace evidence:
  task.created, task.routed, task.started,
  task.completed, task.failed, agent.output

Each event is immutable after creation. Events carry typed payloads
specific to their event type.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Any


@unique
class EventType(str, Enum):
    """Canonical event types — evidence-driven minimum set."""
    TASK_CREATED = "task.created"
    TASK_ROUTED = "task.routed"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    AGENT_OUTPUT = "agent.output"


@unique
class EventScope(str, Enum):
    """Two-tier scoping derived from trace evidence."""
    TASK_LOCAL = "task_local"
    GLOBAL = "global"


@unique
class ConflictClass(str, Enum):
    """Two conflict classes — all traces needed."""
    REPLACEABLE = "replaceable"
    APPEND_ONLY = "append_only"


@dataclass(frozen=True)
class Event:
    """Immutable event record.

    Once created, events are never modified or deleted.
    The event_id is auto-generated. Timestamp is auto-set to now.
    """
    event_type: EventType
    task_id: str
    payload: dict[str, Any]
    scope: EventScope = EventScope.TASK_LOCAL
    conflict_class: ConflictClass = ConflictClass.APPEND_ONLY
    agent_id: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sequence: int = 0  # Set by the event log on append

    def with_sequence(self, seq: int) -> Event:
        """Return a new event with the sequence number set.
        
        Events are frozen, so we create a new instance.
        """
        return Event(
            event_type=self.event_type,
            task_id=self.task_id,
            payload=self.payload,
            scope=self.scope,
            conflict_class=self.conflict_class,
            agent_id=self.agent_id,
            event_id=self.event_id,
            timestamp=self.timestamp,
            sequence=seq,
        )


# ---------------------------------------------------------------------------
# Event factory functions — typed constructors for each event type
# ---------------------------------------------------------------------------


def task_created(
    task_id: str,
    required_capabilities: list[str],
    inputs_available: list[str],
    preferred_capabilities: list[str] | None = None,
    risk_tier: str = "low",
    routing_mode: str = "single",
) -> Event:
    """Emit when pipeline receives a task."""
    return Event(
        event_type=EventType.TASK_CREATED,
        task_id=task_id,
        scope=EventScope.TASK_LOCAL,
        conflict_class=ConflictClass.REPLACEABLE,
        payload={
            "required_capabilities": required_capabilities,
            "inputs_available": inputs_available,
            "preferred_capabilities": preferred_capabilities or [],
            "risk_tier": risk_tier,
            "routing_mode": routing_mode,
        },
    )


def task_routed(
    task_id: str,
    primary_agent_id: str,
    primary_score: float,
    fallback_agent_ids: list[str],
    candidates_evaluated: int,
    candidates_filtered: int,
    reasoning: list[dict[str, Any]] | None = None,
) -> Event:
    """Emit when router returns a result."""
    return Event(
        event_type=EventType.TASK_ROUTED,
        task_id=task_id,
        agent_id=primary_agent_id,
        scope=EventScope.TASK_LOCAL,
        conflict_class=ConflictClass.REPLACEABLE,
        payload={
            "primary_agent_id": primary_agent_id,
            "primary_score": primary_score,
            "fallback_agent_ids": fallback_agent_ids,
            "candidates_evaluated": candidates_evaluated,
            "candidates_filtered": candidates_filtered,
            "reasoning": reasoning or [],
        },
    )


def task_started(
    task_id: str,
    agent_id: str,
    model: str = "",
) -> Event:
    """Emit when agent execution begins."""
    return Event(
        event_type=EventType.TASK_STARTED,
        task_id=task_id,
        agent_id=agent_id,
        scope=EventScope.TASK_LOCAL,
        conflict_class=ConflictClass.REPLACEABLE,
        payload={
            "agent_id": agent_id,
            "model": model,
        },
    )


def task_completed(
    task_id: str,
    agent_id: str,
    tokens_used: int,
    duration_seconds: float,
    output_length: int,
) -> Event:
    """Emit when agent execution succeeds."""
    return Event(
        event_type=EventType.TASK_COMPLETED,
        task_id=task_id,
        agent_id=agent_id,
        scope=EventScope.TASK_LOCAL,
        conflict_class=ConflictClass.REPLACEABLE,
        payload={
            "agent_id": agent_id,
            "tokens_used": tokens_used,
            "duration_seconds": duration_seconds,
            "output_length": output_length,
        },
    )


def task_failed(
    task_id: str,
    stage_failed: str,
    error: str,
    agent_id: str = "",
) -> Event:
    """Emit when task fails at any stage."""
    return Event(
        event_type=EventType.TASK_FAILED,
        task_id=task_id,
        agent_id=agent_id,
        scope=EventScope.TASK_LOCAL,
        conflict_class=ConflictClass.REPLACEABLE,
        payload={
            "stage_failed": stage_failed,
            "error": error,
            "agent_id": agent_id,
        },
    )


def agent_output(
    task_id: str,
    agent_id: str,
    output: str,
    output_type: str = "text",
) -> Event:
    """Emit to store raw agent output."""
    return Event(
        event_type=EventType.AGENT_OUTPUT,
        task_id=task_id,
        agent_id=agent_id,
        scope=EventScope.TASK_LOCAL,
        conflict_class=ConflictClass.APPEND_ONLY,
        payload={
            "agent_id": agent_id,
            "output": output,
            "output_type": output_type,
        },
    )
