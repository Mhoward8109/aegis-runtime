"""Test router failure modes — Contract 2 §2.5.

Routing failures return structured RoutingFailure objects, not exceptions.
Tests all failure paths: no agents, governance blocks, input mismatches,
threshold failures.
"""

import pytest

from aegis.models import AgentSpec, AgentStatus, EvaluationConfig, TrustTier
from aegis.models.enums import RiskTier, RoutingMode
from aegis.registry import AgentRegistry, CapabilityVocabulary, SchemaValidator, TrustRegistry
from aegis.router import (
    TaskDescriptor,
    TaskConstraints,
    RouteResult,
    RoutingFailure,
    RoutingFailureReason,
    RouterConfig,
    route,
)


@pytest.fixture
def vocab():
    return CapabilityVocabulary()


@pytest.fixture
def empty_registry(vocab):
    return AgentRegistry(SchemaValidator(vocab), vocab)


@pytest.fixture
def trust():
    t = TrustRegistry()
    t.set_trust("eng.dev", TrustTier.LOW, "op")
    return t


@pytest.fixture
def registry_with_one(vocab, trust):
    v = SchemaValidator(vocab)
    r = AgentRegistry(v, vocab)
    r.register(AgentSpec(
        agent_id="eng.dev",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Dev",
        capabilities=["build_ui"],
        required_inputs=["task_spec", "design_spec"],
        outputs=["ui_code"], tools=["editor", "special_tool"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
    ))
    return r


class TestNoSuitableAgent:

    def test_unknown_capability(self, empty_registry, trust):
        task = TaskDescriptor.create("t1", ["telekinesis"], ["task_spec"])
        result = route(task, empty_registry, trust)
        assert isinstance(result, RoutingFailure)
        assert result.reason == RoutingFailureReason.NO_SUITABLE_AGENT
        assert "telekinesis" in result.missing_capabilities

    def test_empty_registry(self, empty_registry, trust):
        task = TaskDescriptor.create("t2", ["build_ui"], ["task_spec"])
        result = route(task, empty_registry, trust)
        assert isinstance(result, RoutingFailure)
        assert result.reason == RoutingFailureReason.NO_SUITABLE_AGENT


class TestBlockedByGovernance:

    def test_all_candidates_denied_by_trust(self, registry_with_one, trust):
        # eng.dev has LOW trust. MEDIUM risk → denied.
        task = TaskDescriptor.create(
            "t3", ["build_ui"], ["task_spec", "design_spec"],
            risk_tier=RiskTier.MEDIUM,
        )
        result = route(task, registry_with_one, trust)
        assert isinstance(result, RoutingFailure)
        assert result.reason == RoutingFailureReason.BLOCKED_BY_GOVERNANCE
        assert len(result.denial_reasons) > 0

    def test_critical_risk_always_blocked(self, registry_with_one, trust):
        task = TaskDescriptor.create(
            "t4", ["build_ui"], ["task_spec", "design_spec"],
            risk_tier=RiskTier.CRITICAL,
        )
        result = route(task, registry_with_one, trust)
        assert isinstance(result, RoutingFailure)
        assert result.reason == RoutingFailureReason.BLOCKED_BY_GOVERNANCE


class TestAllCandidatesFiltered:

    def test_missing_inputs_filters_all(self, registry_with_one, trust):
        # Agent requires task_spec + design_spec; we only provide task_spec
        task = TaskDescriptor.create("t5", ["build_ui"], ["task_spec"])
        result = route(task, registry_with_one, trust)
        assert isinstance(result, RoutingFailure)
        assert result.reason == RoutingFailureReason.ALL_CANDIDATES_FILTERED
        assert any("design_spec" in r for r in result.denial_reasons)

    def test_tool_restriction_filters_all(self, registry_with_one, trust):
        # Agent uses special_tool; we restrict to editor only
        task = TaskDescriptor.create(
            "t6", ["build_ui"], ["task_spec", "design_spec"],
            constraints=TaskConstraints(allowed_tools=("editor",)),
        )
        result = route(task, registry_with_one, trust)
        assert isinstance(result, RoutingFailure)
        assert result.reason == RoutingFailureReason.ALL_CANDIDATES_FILTERED


class TestBelowConfidenceThreshold:

    def test_low_scoring_candidates(self, registry_with_one, trust):
        task = TaskDescriptor.create(
            "t7", ["build_ui"], ["task_spec", "design_spec"],
        )
        # Very high threshold
        config = RouterConfig(minimum_confidence_threshold=500.0)
        result = route(task, registry_with_one, trust, config=config)
        assert isinstance(result, RoutingFailure)
        assert result.reason == RoutingFailureReason.BELOW_CONFIDENCE_THRESHOLD
        assert "500.0" in result.detail


class TestFailureStructure:

    def test_failure_has_task_id(self, empty_registry, trust):
        task = TaskDescriptor.create("my-failed-task", ["build_ui"], ["task_spec"])
        result = route(task, empty_registry, trust)
        assert isinstance(result, RoutingFailure)
        assert result.task_id == "my-failed-task"

    def test_failure_has_detail(self, empty_registry, trust):
        task = TaskDescriptor.create("t8", ["build_ui"], ["task_spec"])
        result = route(task, empty_registry, trust)
        assert isinstance(result, RoutingFailure)
        assert isinstance(result.detail, str)
        assert len(result.detail) > 0

    def test_failure_reason_is_enum(self, empty_registry, trust):
        task = TaskDescriptor.create("t9", ["build_ui"], ["task_spec"])
        result = route(task, empty_registry, trust)
        assert isinstance(result, RoutingFailure)
        assert isinstance(result.reason, RoutingFailureReason)

    def test_failures_are_not_exceptions(self, empty_registry, trust):
        """Router never raises for routing logic."""
        task = TaskDescriptor.create("t10", ["build_ui"], ["task_spec"])
        # This should not raise — returns structured failure
        result = route(task, empty_registry, trust)
        assert isinstance(result, RoutingFailure)


class TestTaskDescriptorValidation:

    def test_empty_capabilities_rejected(self):
        with pytest.raises(ValueError, match="required_capabilities"):
            TaskDescriptor.create("t11", [], ["task_spec"])

    def test_empty_task_id_rejected(self):
        with pytest.raises(ValueError, match="task_id"):
            TaskDescriptor.create("", ["build_ui"], ["task_spec"])

    def test_invalid_priority_rejected(self):
        with pytest.raises(ValueError, match="priority"):
            TaskDescriptor.create(
                "t12", ["build_ui"], ["task_spec"],
                priority="urgent",
            )

    def test_valid_descriptor_constructs(self):
        task = TaskDescriptor.create("t13", ["build_ui"], ["task_spec"])
        assert task.task_id == "t13"
        assert task.required_capabilities == ("build_ui",)
        assert task.routing_mode == RoutingMode.SINGLE
