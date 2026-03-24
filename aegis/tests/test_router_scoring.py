"""Test router scoring — Contract 2 §2.3 step 2.

Tests individual scoring functions: capability match, specialization bonus,
cost risk, and stub behavior for context/historical scoring.
"""

import pytest

from aegis.models import AgentSpec, AgentStatus, EvaluationConfig, EnvironmentConfig
from aegis.router import (
    TaskDescriptor,
    NullExperienceStore,
    NullContextStore,
    score_capability_match,
    score_context_relevance,
    score_cost_risk,
    score_historical_performance,
    compute_total_score,
)
from aegis.router.scoring import ExperienceStore


def _make_agent(
    agent_id: str = "test.agent",
    capabilities: list[str] | None = None,
    max_execution_seconds: int = 120,
) -> AgentSpec:
    return AgentSpec(
        agent_id=agent_id,
        version="1.0.0", status=AgentStatus.ACTIVE, role="Test",
        capabilities=capabilities or ["build_ui"],
        required_inputs=["task_spec"], outputs=["output"], tools=[], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
        environment=EnvironmentConfig(max_execution_seconds=max_execution_seconds),
    )


class TestCapabilityMatch:

    def test_preferred_match_scored(self):
        task = TaskDescriptor.create(
            "t1", ["build_ui"],
            ["task_spec"],
            preferred_capabilities=["integrate_api", "optimize_rendering"],
        )
        agent = _make_agent(capabilities=["build_ui", "integrate_api"])
        reasons = score_capability_match(task, agent)
        pref = [r for r in reasons if r.factor == "preferred_capability"]
        assert len(pref) == 1
        assert pref[0].delta == 25.0  # 1 match × 25

    def test_multiple_preferred_matches(self):
        task = TaskDescriptor.create(
            "t2", ["build_ui"],
            ["task_spec"],
            preferred_capabilities=["integrate_api", "optimize_rendering"],
        )
        agent = _make_agent(capabilities=["build_ui", "integrate_api", "optimize_rendering"])
        reasons = score_capability_match(task, agent)
        pref = [r for r in reasons if r.factor == "preferred_capability"]
        assert pref[0].delta == 50.0  # 2 matches × 25

    def test_no_preferred_no_score(self):
        task = TaskDescriptor.create("t3", ["build_ui"], ["task_spec"])
        agent = _make_agent()
        reasons = score_capability_match(task, agent)
        pref = [r for r in reasons if r.factor == "preferred_capability"]
        assert len(pref) == 0


class TestSpecializationBonus:

    def test_high_overlap_gets_bonus(self):
        task = TaskDescriptor.create(
            "t4", ["build_ui"],
            ["task_spec"],
            preferred_capabilities=["integrate_api"],
        )
        # Agent has 2 caps, both match task caps → overlap = 1.0
        agent = _make_agent(capabilities=["build_ui", "integrate_api"])
        reasons = score_capability_match(task, agent)
        spec = [r for r in reasons if r.factor == "specialization"]
        assert len(spec) == 1
        assert spec[0].delta == 15.0

    def test_low_overlap_no_bonus(self):
        task = TaskDescriptor.create("t5", ["build_ui"], ["task_spec"])
        # Agent has 5 caps but only 1 matches → overlap = 0.2
        agent = _make_agent(capabilities=[
            "build_ui", "write_backend", "design_schema",
            "deploy_service", "monitor_security",
        ])
        reasons = score_capability_match(task, agent)
        spec = [r for r in reasons if r.factor == "specialization"]
        assert len(spec) == 0


class TestCostRisk:

    def test_high_time_ratio_penalized(self):
        task = TaskDescriptor.create("t6", ["build_ui"], ["task_spec"])
        # Default task budget: 120s. Agent timeout: 300s → ratio = 2.5
        agent = _make_agent(max_execution_seconds=300)
        reasons = score_cost_risk(task, agent, NullExperienceStore())
        cost = [r for r in reasons if r.factor == "cost_time_ratio"]
        assert len(cost) == 1
        assert cost[0].delta == -20.0

    def test_low_time_ratio_no_penalty(self):
        task = TaskDescriptor.create("t7", ["build_ui"], ["task_spec"])
        # Agent timeout: 60s, budget: 120s → ratio = 0.5
        agent = _make_agent(max_execution_seconds=60)
        reasons = score_cost_risk(task, agent, NullExperienceStore())
        cost = [r for r in reasons if r.factor == "cost_time_ratio"]
        assert len(cost) == 0


class TestStubBehavior:
    """Null stores return empty — no scoring contribution."""

    def test_null_experience_store_returns_nothing(self):
        task = TaskDescriptor.create("t8", ["build_ui"], ["task_spec"])
        agent = _make_agent()
        reasons = score_historical_performance(task, agent, NullExperienceStore())
        assert reasons == []

    def test_null_context_store_returns_nothing(self):
        task = TaskDescriptor.create("t9", ["build_ui"], ["task_spec"])
        agent = _make_agent()
        reasons = score_context_relevance(task, agent, NullContextStore())
        assert reasons == []

    def test_live_experience_store_contributes_score(self):
        """Prove that a real store implementation will be picked up."""

        class FakeStore:
            def success_rate(self, agent_id, task_type):
                return 0.9

            def average_latency(self, agent_id, task_type):
                return 5.0

            def median_latency(self, task_type):
                return 3.0

            def recent_failure(self, agent_id, task_type, last_n):
                return True

            def flagged_for_overruns(self, agent_id):
                return False

        task = TaskDescriptor.create("t10", ["build_ui"], ["task_spec"])
        agent = _make_agent()
        reasons = score_historical_performance(task, agent, FakeStore())

        success = [r for r in reasons if r.factor == "historical_success_rate"]
        assert len(success) == 1
        assert success[0].delta == pytest.approx(36.0)  # 40 × 0.9

        latency = [r for r in reasons if r.factor == "latency_penalty"]
        assert len(latency) == 1
        assert latency[0].delta == pytest.approx(-2.0)  # 5.0 - 3.0

        failure = [r for r in reasons if r.factor == "failure_recency"]
        assert len(failure) == 1
        assert failure[0].delta == -50.0


class TestComputeTotal:

    def test_sums_deltas(self):
        from aegis.router.types import RoutingReason
        reasons = [
            RoutingReason("a", 25.0, ""),
            RoutingReason("b", 15.0, ""),
            RoutingReason("c", -20.0, ""),
        ]
        assert compute_total_score(reasons) == 20.0

    def test_empty_list_returns_zero(self):
        assert compute_total_score([]) == 0.0
