"""Test router ranked output — Contract 2 §2.3 steps 3-4.

Tests the full route() function: ranking, primary/fallback selection,
routing modes, confidence threshold, and result structure.
"""

import pytest

from aegis.models import AgentSpec, AgentStatus, EvaluationConfig, EnvironmentConfig, TrustTier
from aegis.models.enums import RiskTier, RoutingMode
from aegis.registry import AgentRegistry, CapabilityVocabulary, SchemaValidator, TrustRegistry
from aegis.router import (
    TaskDescriptor,
    TaskBudget,
    RouteResult,
    RoutingFailure,
    RouterConfig,
    route,
)


@pytest.fixture
def vocab():
    return CapabilityVocabulary()


@pytest.fixture
def trust():
    t = TrustRegistry()
    t.set_trust("eng.senior", TrustTier.HIGH, "op")
    t.set_trust("eng.mid", TrustTier.MEDIUM, "op")
    t.set_trust("eng.junior", TrustTier.LOW, "op")
    return t


@pytest.fixture
def registry(vocab):
    v = SchemaValidator(vocab)
    r = AgentRegistry(v, vocab)

    # Senior: high capability match, specialist
    r.register(AgentSpec(
        agent_id="eng.senior",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Senior",
        capabilities=["build_ui", "integrate_api"],
        required_inputs=["task_spec"], outputs=["ui_code"],
        tools=["editor"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
        environment=EnvironmentConfig(max_execution_seconds=60),
    ))
    # Mid: has preferred cap, less specialized
    r.register(AgentSpec(
        agent_id="eng.mid",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Mid",
        capabilities=["build_ui", "integrate_api", "write_tests", "review_code"],
        required_inputs=["task_spec"], outputs=["ui_code"],
        tools=["editor"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
        environment=EnvironmentConfig(max_execution_seconds=120),
    ))
    # Junior: minimal capabilities
    r.register(AgentSpec(
        agent_id="eng.junior",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Junior",
        capabilities=["build_ui"],
        required_inputs=["task_spec"], outputs=["ui_code"],
        tools=["editor"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
        environment=EnvironmentConfig(max_execution_seconds=90),
    ))

    return r


class TestPrimarySelection:

    def test_highest_score_is_primary(self, registry, trust):
        task = TaskDescriptor.create(
            "t1", ["build_ui"], ["task_spec"],
            preferred_capabilities=["integrate_api"],
        )
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        # Senior has preferred match + specialization → highest
        assert result.primary.agent_id == "eng.senior"

    def test_primary_has_score_and_reasons(self, registry, trust):
        task = TaskDescriptor.create(
            "t2", ["build_ui"], ["task_spec"],
            preferred_capabilities=["integrate_api"],
        )
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        assert result.primary.score > 0
        assert len(result.primary.reasons) > 0


class TestFallbackSelection:

    def test_fallbacks_are_ranked(self, registry, trust):
        task = TaskDescriptor.create(
            "t3", ["build_ui"], ["task_spec"],
            preferred_capabilities=["integrate_api"],
        )
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        assert len(result.fallbacks) >= 1
        # Fallbacks should be lower-scored than primary
        for fb in result.fallbacks:
            assert fb.score <= result.primary.score

    def test_max_fallbacks_respected(self, registry, trust):
        task = TaskDescriptor.create("t4", ["build_ui"], ["task_spec"])
        config = RouterConfig(max_fallbacks=1, minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        assert len(result.fallbacks) <= 1


class TestAllCandidates:

    def test_all_candidates_in_result(self, registry, trust):
        task = TaskDescriptor.create("t5", ["build_ui"], ["task_spec"])
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        # Should include all active build_ui agents that pass filters
        assert result.candidates_evaluated >= 2

    def test_all_candidates_sorted_descending(self, registry, trust):
        task = TaskDescriptor.create("t6", ["build_ui"], ["task_spec"])
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        scores = [c.score for c in result.all_candidates]
        assert scores == sorted(scores, reverse=True)


class TestRoutingModes:

    def test_single_mode_in_result(self, registry, trust):
        task = TaskDescriptor.create(
            "t7", ["build_ui"], ["task_spec"],
            routing_mode=RoutingMode.SINGLE,
        )
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        assert result.routing_mode == RoutingMode.SINGLE

    def test_ranked_mode_in_result(self, registry, trust):
        task = TaskDescriptor.create(
            "t8", ["build_ui"], ["task_spec"],
            routing_mode=RoutingMode.RANKED,
        )
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        assert result.routing_mode == RoutingMode.RANKED
        # Ranked mode still returns primary + fallbacks; orchestrator decides
        assert result.primary is not None


class TestConfidenceThreshold:

    def test_below_threshold_returns_failure(self, registry, trust):
        task = TaskDescriptor.create("t9", ["build_ui"], ["task_spec"])
        # Set threshold impossibly high
        config = RouterConfig(minimum_confidence_threshold=9999.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RoutingFailure)
        assert result.reason.value == "below_confidence_threshold"

    def test_above_threshold_succeeds(self, registry, trust):
        task = TaskDescriptor.create(
            "t10", ["build_ui"], ["task_spec"],
            preferred_capabilities=["integrate_api"],
        )
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)


class TestResultMetadata:

    def test_candidates_evaluated_count(self, registry, trust):
        task = TaskDescriptor.create("t11", ["build_ui"], ["task_spec"])
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        assert result.candidates_evaluated >= 2

    def test_candidates_filtered_count(self, registry, trust):
        task = TaskDescriptor.create(
            "t12", ["build_ui"], ["task_spec"],
            risk_tier=RiskTier.MEDIUM,
        )
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        # Junior (LOW trust) should be filtered for MEDIUM risk
        assert result.candidates_filtered >= 1

    def test_task_id_propagated(self, registry, trust):
        task = TaskDescriptor.create("my-task-123", ["build_ui"], ["task_spec"])
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        assert result.task_id == "my-task-123"

    def test_reason_summary_readable(self, registry, trust):
        task = TaskDescriptor.create(
            "t13", ["build_ui"], ["task_spec"],
            preferred_capabilities=["integrate_api"],
        )
        config = RouterConfig(minimum_confidence_threshold=0.0)
        result = route(task, registry, trust, config=config)
        assert isinstance(result, RouteResult)
        summary = result.primary.reason_summary
        assert isinstance(summary, str)
        assert len(summary) > 0
