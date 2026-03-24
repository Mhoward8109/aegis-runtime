"""Event Log — State Authority P1b.

Append-only, monotonically ordered, replayable event log.

Supports:
  - Append with automatic sequence numbering
  - Fetch by task_id (task-local scope)
  - Fetch by agent_id (cross-task, for experience store)
  - Fetch all (global scope)
  - Replay: iterate events in order

Does NOT support:
  - Mutation or deletion of events
  - Snapshots (deferred — event streams are small)
  - Archival (deferred — no retention pressure yet)
  - Multi-writer sequencing (single-threaded for now)
"""

from __future__ import annotations

from aegis.state.event import Event, EventScope


class EventLog:
    """Append-only event log with monotonic sequencing.

    Thread safety: Not thread-safe. Single-writer assumption.
    When parallelism is needed, wrap in a lock or replace with
    a sequencer (deferred to P2).
    """

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._next_sequence: int = 1

        # Indexes for fast lookup
        self._by_task: dict[str, list[int]] = {}   # task_id → list of indexes
        self._by_agent: dict[str, list[int]] = {}   # agent_id → list of indexes

    def append(self, event: Event) -> Event:
        """Append an event to the log.

        Assigns a monotonic sequence number. Returns the sequenced event.
        The original event is not modified (events are frozen).
        """
        sequenced = event.with_sequence(self._next_sequence)
        self._next_sequence += 1

        idx = len(self._events)
        self._events.append(sequenced)

        # Update indexes
        if sequenced.task_id:
            if sequenced.task_id not in self._by_task:
                self._by_task[sequenced.task_id] = []
            self._by_task[sequenced.task_id].append(idx)

        if sequenced.agent_id:
            if sequenced.agent_id not in self._by_agent:
                self._by_agent[sequenced.agent_id] = []
            self._by_agent[sequenced.agent_id].append(idx)

        return sequenced

    def get_by_task(self, task_id: str) -> list[Event]:
        """Fetch all events for a task, in order."""
        indexes = self._by_task.get(task_id, [])
        return [self._events[i] for i in indexes]

    def get_by_agent(self, agent_id: str) -> list[Event]:
        """Fetch all events involving an agent, across all tasks."""
        indexes = self._by_agent.get(agent_id, [])
        return [self._events[i] for i in indexes]

    def get_all(self) -> list[Event]:
        """Fetch all events in sequence order."""
        return list(self._events)

    def replay(self, task_id: str | None = None) -> list[Event]:
        """Replay events in order. Optionally filtered by task_id.

        This is the foundation for projection rebuilds.
        """
        if task_id:
            return self.get_by_task(task_id)
        return self.get_all()

    @property
    def size(self) -> int:
        """Total number of events in the log."""
        return len(self._events)

    @property
    def last_sequence(self) -> int:
        """Most recent sequence number (0 if empty)."""
        return self._next_sequence - 1

    def task_ids(self) -> set[str]:
        """All task IDs that have events."""
        return set(self._by_task.keys())

    def agent_ids(self) -> set[str]:
        """All agent IDs that have events."""
        return set(self._by_agent.keys())
