"""Test State Authority — P1b.

Tests event model, append-only log, task lifecycle projection,
agent execution history projection, replay correctness, and
router integration (experience store protocol).
"""

import pytest

from aegis.state import (
    StateAuthority,
    EventType,
    EventScope,
    TaskState,
    AgentHistory,
    task_created,
    task_routed,
    task_started,
    task_completed,
    task_failed,
    agent_output,
)


@pytest.fixture
def sa() -> StateAuthority:
    return StateAuthority()


def _emit_successful_task(sa: StateAuthority, task_id: str, agent_id: str, tokens: int = 500, duration: float = 5.0) -> None:
    """Helper: emit full lifecycle for a successful task."""
    sa.record(task_created(task_id, ["review_code"], ["code"]))
    sa.record(task_routed(task_id, agent_id, 20.0, [], 2, 0))
    sa.record(task_started(task_id, agent_id, "claude-sonnet-4-20250514"))
    sa.record(agent_output(task_id, agent_id, "Some output text"))
    sa.record(task_completed(task_id, agent_id, tokens, duration, 16))


def _emit_failed_task(sa: StateAuthority, task_id: str, agent_id: str = "", stage: str = "routing") -> None:
    """Helper: emit lifecycle for a failed task."""
    sa.record(task_created(task_id, ["deploy_service"], ["code"]))
    sa.record(task_failed(task_id, stage, "no suitable agent", agent_id))


# ---------------------------------------------------------------------------
# Event Model Tests
# ---------------------------------------------------------------------------


class TestEventModel:

    def test_event_types_exist(self):
        assert EventType.TASK_CREATED.value == "task.created"
        assert EventType.TASK_ROUTED.value == "task.routed"
        assert EventType.TASK_STARTED.value == "task.started"
        assert EventType.TASK_COMPLETED.value == "task.completed"
        assert EventType.TASK_FAILED.value == "task.failed"
        assert EventType.AGENT_OUTPUT.value == "agent.output"

    def test_factory_creates_correct_type(self):
        e = task_created("t1", ["review_code"], ["code"])
        assert e.event_type == EventType.TASK_CREATED
        assert e.task_id == "t1"
        assert e.payload["required_capabilities"] == ["review_code"]

    def test_events_are_immutable(self):
        e = task_created("t1", ["review_code"], ["code"])
        with pytest.raises(AttributeError):
            e.task_id = "t2"

    def test_event_has_auto_id_and_timestamp(self):
        e = task_created("t1", ["review_code"], ["code"])
        assert e.event_id  # non-empty
        assert e.timestamp  # non-empty

    def test_sequence_set_by_log(self):
        e = task_created("t1", ["review_code"], ["code"])
        assert e.sequence == 0  # not yet sequenced
        sequenced = e.with_sequence(42)
        assert sequenced.sequence == 42
        assert e.sequence == 0  # original unchanged


# ---------------------------------------------------------------------------
# Event Log Tests
# ---------------------------------------------------------------------------


class TestEventLog:

    def test_append_assigns_sequence(self, sa):
        e = sa.log.append(task_created("t1", ["review_code"], ["code"]))
        assert e.sequence == 1

    def test_monotonic_ordering(self, sa):
        e1 = sa.log.append(task_created("t1", ["review_code"], ["code"]))
        e2 = sa.log.append(task_started("t1", "agent.a"))
        e3 = sa.log.append(task_completed("t1", "agent.a", 100, 1.0, 50))
        assert e1.sequence < e2.sequence < e3.sequence

    def test_fetch_by_task(self, sa):
        sa.record(task_created("t1", ["review_code"], ["code"]))
        sa.record(task_created("t2", ["design_schema"], ["spec"]))
        sa.record(task_started("t1", "agent.a"))

        t1_events = sa.log.get_by_task("t1")
        assert len(t1_events) == 2
        assert all(e.task_id == "t1" for e in t1_events)

    def test_fetch_by_agent(self, sa):
        sa.record(task_started("t1", "agent.a"))
        sa.record(task_started("t2", "agent.b"))
        sa.record(task_completed("t1", "agent.a", 100, 1.0, 50))

        a_events = sa.log.get_by_agent("agent.a")
        assert len(a_events) == 2
        assert all(e.agent_id == "agent.a" for e in a_events)

    def test_size_and_task_ids(self, sa):
        _emit_successful_task(sa, "t1", "agent.a")
        _emit_failed_task(sa, "t2")
        assert sa.log.size == 7  # 5 for success + 2 for failure
        assert sa.log.task_ids() == {"t1", "t2"}

    def test_empty_log(self, sa):
        assert sa.log.size == 0
        assert sa.log.get_by_task("nonexistent") == []
        assert sa.log.last_sequence == 0


# ---------------------------------------------------------------------------
# Task Lifecycle Projection Tests
# ---------------------------------------------------------------------------


class TestTaskLifecycleProjection:

    def test_created_state(self, sa):
        sa.record(task_created("t1", ["review_code"], ["code"], risk_tier="low"))
        state = sa.get_task("t1")
        assert state is not None
        assert state.status == "created"
        assert state.required_capabilities == ["review_code"]

    def test_full_successful_lifecycle(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer", tokens=384, duration=6.3)
        state = sa.get_task("t1")
        assert state.status == "completed"
        assert state.agent_id == "eng.reviewer"
        assert state.tokens_used == 384
        assert state.duration_seconds == 6.3
        assert state.output == "Some output text"
        assert state.event_count == 5

    def test_failed_lifecycle(self, sa):
        _emit_failed_task(sa, "t1", stage="routing")
        state = sa.get_task("t1")
        assert state.status == "failed"
        assert state.stage_failed == "routing"
        assert state.error == "no suitable agent"

    def test_routed_state_captures_routing_detail(self, sa):
        sa.record(task_created("t1", ["review_code"], ["code"]))
        sa.record(task_routed("t1", "eng.reviewer", 20.0, ["eng.explainer"], 2, 0,
                              reasoning=[{"factor": "preferred", "delta": 25.0, "detail": "matched"}]))
        state = sa.get_task("t1")
        assert state.status == "routed"
        assert state.primary_agent_id == "eng.reviewer"
        assert state.primary_score == 20.0
        assert state.fallback_agent_ids == ["eng.explainer"]
        assert len(state.routing_reasoning) == 1

    def test_unknown_task_returns_none(self, sa):
        assert sa.get_task("nonexistent") is None

    def test_list_tasks_by_status(self, sa):
        _emit_successful_task(sa, "t1", "agent.a")
        _emit_failed_task(sa, "t2")
        sa.record(task_created("t3", ["build_ui"], ["spec"]))

        completed = sa.tasks.list_tasks("completed")
        assert len(completed) == 1
        assert completed[0].task_id == "t1"

        failed = sa.tasks.list_tasks("failed")
        assert len(failed) == 1

        created = sa.tasks.list_tasks("created")
        assert len(created) == 1


# ---------------------------------------------------------------------------
# Agent Execution History Projection Tests
# ---------------------------------------------------------------------------


class TestAgentExecutionHistory:

    def test_completed_task_recorded(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer")
        history = sa.get_agent_history("eng.reviewer")
        assert history is not None
        assert history.total_tasks == 1
        assert history.completed_tasks == 1
        assert history.failed_tasks == 0

    def test_failed_dispatch_recorded(self, sa):
        sa.record(task_created("t1", ["review_code"], ["code"]))
        sa.record(task_routed("t1", "eng.reviewer", 10.0, [], 1, 0))
        sa.record(task_started("t1", "eng.reviewer"))
        sa.record(task_failed("t1", "dispatch", "API error", "eng.reviewer"))

        history = sa.get_agent_history("eng.reviewer")
        assert history is not None
        assert history.total_tasks == 1
        assert history.failed_tasks == 1

    def test_routing_failure_not_recorded_against_agent(self, sa):
        _emit_failed_task(sa, "t1", agent_id="", stage="routing")
        # No agent was involved, so no agent history
        assert sa.agent_history.list_agents() == []

    def test_success_rate_by_type(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer")
        _emit_successful_task(sa, "t2", "eng.reviewer")
        sa.record(task_created("t3", ["review_code"], ["code"]))
        sa.record(task_started("t3", "eng.reviewer"))
        sa.record(task_failed("t3", "dispatch", "error", "eng.reviewer"))

        rate = sa.agent_history.success_rate("eng.reviewer", "review_code")
        assert rate is not None
        assert abs(rate - 2/3) < 0.01

    def test_average_latency(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer", duration=6.0)
        _emit_successful_task(sa, "t2", "eng.reviewer", duration=10.0)

        avg = sa.agent_history.average_latency("eng.reviewer", "review_code")
        assert avg == 8.0

    def test_median_latency_across_agents(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer", duration=6.0)
        _emit_successful_task(sa, "t2", "eng.explainer", duration=10.0)

        median = sa.agent_history.median_latency("review_code")
        assert median == 8.0  # median of [6.0, 10.0]

    def test_recent_failure_detection(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer")
        sa.record(task_created("t2", ["review_code"], ["code"]))
        sa.record(task_started("t2", "eng.reviewer"))
        sa.record(task_failed("t2", "dispatch", "error", "eng.reviewer"))

        assert sa.agent_history.recent_failure("eng.reviewer", "review_code", 3) is True

    def test_unknown_agent_returns_none(self, sa):
        assert sa.agent_history.success_rate("unknown.agent", "anything") is None
        assert sa.agent_history.average_latency("unknown.agent", "anything") is None
        assert sa.agent_history.recent_failure("unknown.agent", "anything") is False


# ---------------------------------------------------------------------------
# Replay Tests
# ---------------------------------------------------------------------------


class TestReplay:

    def test_replay_task_matches_live_state(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer", tokens=500, duration=5.0)

        live_state = sa.get_task("t1")
        replayed_state = sa.replay_task("t1")

        assert replayed_state is not None
        assert replayed_state.status == live_state.status
        assert replayed_state.agent_id == live_state.agent_id
        assert replayed_state.tokens_used == live_state.tokens_used
        assert replayed_state.output == live_state.output

    def test_replay_all_rebuilds_projections(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer")
        _emit_successful_task(sa, "t2", "eng.explainer")
        _emit_failed_task(sa, "t3")

        # Clear projections
        sa.tasks.clear()
        sa.agent_history.clear()
        assert sa.get_task("t1") is None

        # Replay
        sa.replay_all()
        assert sa.get_task("t1") is not None
        assert sa.get_task("t1").status == "completed"
        assert sa.get_task("t3").status == "failed"
        assert sa.get_agent_history("eng.reviewer").total_tasks == 1

    def test_replay_nonexistent_task_returns_none(self, sa):
        assert sa.replay_task("nonexistent") is None


# ---------------------------------------------------------------------------
# Scoping Tests
# ---------------------------------------------------------------------------


class TestScoping:

    def test_task_events_isolated(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer")
        _emit_successful_task(sa, "t2", "eng.explainer")

        t1_events = sa.log.get_by_task("t1")
        t2_events = sa.log.get_by_task("t2")
        assert all(e.task_id == "t1" for e in t1_events)
        assert all(e.task_id == "t2" for e in t2_events)
        assert len(t1_events) == 5
        assert len(t2_events) == 5

    def test_agent_history_crosses_tasks(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer")
        _emit_successful_task(sa, "t2", "eng.reviewer")

        history = sa.get_agent_history("eng.reviewer")
        assert history.total_tasks == 2  # global scope


# ---------------------------------------------------------------------------
# Router Integration Tests (ExperienceStore protocol)
# ---------------------------------------------------------------------------


class TestExperienceStoreProtocol:
    """Prove agent_history implements ExperienceStore without adapter code."""

    def test_success_rate_protocol(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer")
        store = sa.experience_store
        rate = store.success_rate("eng.reviewer", "review_code")
        assert rate == 1.0

    def test_average_latency_protocol(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer", duration=5.0)
        store = sa.experience_store
        avg = store.average_latency("eng.reviewer", "review_code")
        assert avg == 5.0

    def test_median_latency_protocol(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer", duration=5.0)
        _emit_successful_task(sa, "t2", "eng.explainer", duration=10.0)
        store = sa.experience_store
        median = store.median_latency("review_code")
        assert median == 7.5

    def test_recent_failure_protocol(self, sa):
        _emit_successful_task(sa, "t1", "eng.reviewer")
        store = sa.experience_store
        assert store.recent_failure("eng.reviewer", "review_code") is False

    def test_flagged_for_overruns_protocol(self, sa):
        store = sa.experience_store
        assert store.flagged_for_overruns("eng.reviewer") is False

    def test_null_returns_for_unknown(self, sa):
        store = sa.experience_store
        assert store.success_rate("unknown", "x") is None
        assert store.average_latency("unknown", "x") is None
        assert store.median_latency("nonexistent_type") is None
        assert store.recent_failure("unknown", "x") is False
