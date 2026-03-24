"""State Authority — P1b facade.

Wires the event log and projections into a single entry point.
The harness and future orchestrator interact with this, not the
individual components directly.
"""

from __future__ import annotations

from aegis.state.event import Event
from aegis.state.event_log import EventLog
from aegis.state.task_lifecycle_projection import TaskLifecycleProjection, TaskState
from aegis.state.agent_history_projection import AgentExecutionHistoryProjection, AgentHistory


class StateAuthority:
    """Minimum viable state layer.

    Owns the event log and both projections. Every event appended
    to the log is automatically applied to all projections.

    The agent_history projection implements ExperienceStore,
    so it can be passed directly to the router for scoring.
    """

    def __init__(self) -> None:
        self.log = EventLog()
        self.tasks = TaskLifecycleProjection()
        self.agent_history = AgentExecutionHistoryProjection()

    def record(self, event: Event) -> Event:
        """Record an event: append to log, apply to all projections.

        Returns the sequenced event.
        """
        sequenced = self.log.append(event)
        self.tasks.apply(sequenced)
        self.agent_history.apply(sequenced)
        return sequenced

    def get_task(self, task_id: str) -> TaskState | None:
        """Get current task state."""
        return self.tasks.get(task_id)

    def get_agent_history(self, agent_id: str) -> AgentHistory | None:
        """Get agent execution history."""
        return self.agent_history.get_history(agent_id)

    def replay_task(self, task_id: str) -> TaskState | None:
        """Rebuild task state from event log replay.

        Independent of cached projection state — replays from scratch.
        """
        events = self.log.get_by_task(task_id)
        if not events:
            return None
        return self.tasks.rebuild(events)

    def replay_all(self) -> None:
        """Rebuild all projections from the full event log.

        Clears projection caches and replays every event.
        """
        self.tasks.clear()
        self.agent_history.clear()
        for event in self.log.get_all():
            self.tasks.apply(event)
            self.agent_history.apply(event)

    @property
    def event_count(self) -> int:
        return self.log.size

    @property
    def task_count(self) -> int:
        return len(self.log.task_ids())

    @property
    def experience_store(self) -> AgentExecutionHistoryProjection:
        """Return the agent history projection as an ExperienceStore.

        This is the interface the router consumes for scoring.
        No adapter needed — AgentExecutionHistoryProjection implements
        the ExperienceStore protocol directly.
        """
        return self.agent_history
