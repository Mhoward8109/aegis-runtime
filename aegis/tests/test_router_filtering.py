"""Test router filtering — Contract 2 §2.3 step 1.

Tests the filter phase: status, capabilities, required inputs,
tool constraints, and admission checks.
"""

import pytest

from aegis.models import AgentSpec, AgentStatus, EvaluationConfig, TrustTier
from aegis.registry import AgentRegistry, CapabilityVocabulary, SchemaValidator, TrustRegistry
from aegis.router import (
    TaskDescriptor,
    TaskConstraints,
    filter_candidates,
    default_admission_check,
)
from aegis.models.enums import RiskTier


@pytest.fixture
def vocab():
    return CapabilityVocabulary()


@pytest.fixture
def trust():
    t = TrustRegistry()
    t.set_trust("eng.frontend", TrustTier.MEDIUM, "op")
    t.set_trust("eng.backend", TrustTier.HIGH, "op")
    # eng.junior has no entry → LOW
    return t


@pytest.fixture
def registry(vocab):
    v = SchemaValidator(vocab)
    r = AgentRegistry(v, vocab)

    r.register(AgentSpec(
        agent_id="eng.frontend",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Frontend",
        capabilities=["build_ui", "integrate_api"],
        required_inputs=["task_spec"],
        outputs=["ui_code"], tools=["editor", "linter"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
    ))
    r.register(AgentSpec(
        agent_id="eng.backend",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Backend",
        capabilities=["write_backend", "integrate_api"],
        required_inputs=["task_spec", "api_schema"],
        outputs=["backend_code"], tools=["editor", "linter", "db_tool"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
    ))
    r.register(AgentSpec(
        agent_id="eng.junior",
        version="1.0.0", status=AgentStatus.ACTIVE, role="Junior",
        capabilities=["build_ui"],
        required_inputs=["task_spec"],
        outputs=["ui_code"], tools=["editor"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
    ))
    r.register(AgentSpec(
        agent_id="legacy.builder",
        version="1.0.0", status=AgentStatus.DEPRECATED, role="Legacy",
        capabilities=["build_ui"],
        required_inputs=["task_spec"],
        outputs=["ui_code"], tools=["editor"], constraints=[],
        evaluation=EvaluationConfig(success_criteria=["pass"]),
    ))
    return r


class TestCapabilityFiltering:

    def test_single_capability_match(self, registry, trust):
        task = TaskDescriptor.create("t1", ["build_ui"], ["task_spec"])
        result = filter_candidates(task, registry, trust)
        ids = {a.agent_id for a in result.passed}
        assert "eng.frontend" in ids
        assert "eng.junior" in ids

    def test_multi_capability_intersection(self, registry, trust):
        task = TaskDescriptor.create("t2", ["build_ui", "integrate_api"], ["task_spec"])
        result = filter_candidates(task, registry, trust)
        assert len(result.passed) == 1
        assert result.passed[0].agent_id == "eng.frontend"

    def test_no_match_returns_empty(self, registry, trust):
        task = TaskDescriptor.create("t3", ["deploy_service"], ["task_spec"])
        result = filter_candidates(task, registry, trust)
        assert len(result.passed) == 0


class TestStatusFiltering:

    def test_deprecated_excluded(self, registry, trust):
        task = TaskDescriptor.create("t4", ["build_ui"], ["task_spec"])
        result = filter_candidates(task, registry, trust)
        ids = {a.agent_id for a in result.passed}
        assert "legacy.builder" not in ids

    def test_only_active_returned(self, registry, trust):
        task = TaskDescriptor.create("t5", ["build_ui"], ["task_spec"])
        result = filter_candidates(task, registry, trust)
        for agent in result.passed:
            assert agent.status == AgentStatus.ACTIVE


class TestInputFiltering:

    def test_missing_required_input_excluded(self, registry, trust):
        task = TaskDescriptor.create("t6", ["integrate_api"], ["task_spec"])
        result = filter_candidates(task, registry, trust)
        ids = {a.agent_id for a in result.passed}
        # backend requires api_schema which is missing
        assert "eng.backend" not in ids
        # frontend only requires task_spec
        assert "eng.frontend" in ids

    def test_all_inputs_available(self, registry, trust):
        task = TaskDescriptor.create("t7", ["integrate_api"], ["task_spec", "api_schema"])
        result = filter_candidates(task, registry, trust)
        ids = {a.agent_id for a in result.passed}
        assert "eng.frontend" in ids
        assert "eng.backend" in ids


class TestToolConstraintFiltering:

    def test_tool_restriction_excludes(self, registry, trust):
        task = TaskDescriptor.create(
            "t8", ["integrate_api"], ["task_spec", "api_schema"],
            constraints=TaskConstraints(allowed_tools=("editor", "linter")),
        )
        result = filter_candidates(task, registry, trust)
        ids = {a.agent_id for a in result.passed}
        # backend uses db_tool which isn't in allowed set
        assert "eng.backend" not in ids
        assert "eng.frontend" in ids

    def test_no_tool_restriction_allows_all(self, registry, trust):
        task = TaskDescriptor.create(
            "t9", ["integrate_api"], ["task_spec", "api_schema"],
            constraints=TaskConstraints(allowed_tools=None),
        )
        result = filter_candidates(task, registry, trust)
        ids = {a.agent_id for a in result.passed}
        assert "eng.backend" in ids
        assert "eng.frontend" in ids


class TestAdmissionFiltering:

    def test_low_trust_blocked_for_medium_risk(self, registry, trust):
        task = TaskDescriptor.create(
            "t10", ["build_ui"], ["task_spec"],
            risk_tier=RiskTier.MEDIUM,
        )
        result = filter_candidates(task, registry, trust)
        ids = {a.agent_id for a in result.passed}
        # junior has LOW trust → blocked for MEDIUM risk
        assert "eng.junior" not in ids
        # frontend has MEDIUM trust → admitted
        assert "eng.frontend" in ids

    def test_critical_risk_blocks_all(self, registry, trust):
        task = TaskDescriptor.create(
            "t11", ["build_ui"], ["task_spec"],
            risk_tier=RiskTier.CRITICAL,
        )
        result = filter_candidates(task, registry, trust)
        assert len(result.passed) == 0
        assert len(result.denial_reasons) > 0

    def test_custom_admission_function(self, registry, trust):
        def deny_all(task, agent, trust_tier):
            return False, "custom denial"

        task = TaskDescriptor.create("t12", ["build_ui"], ["task_spec"])
        result = filter_candidates(task, registry, trust, admission_check=deny_all)
        assert len(result.passed) == 0


class TestFilterMetadata:

    def test_counts_correct(self, registry, trust):
        task = TaskDescriptor.create(
            "t13", ["build_ui"], ["task_spec"],
            risk_tier=RiskTier.MEDIUM,
        )
        result = filter_candidates(task, registry, trust)
        # 2 active build_ui agents evaluated (frontend, junior; legacy excluded by status)
        assert result.total_evaluated == 2
        # junior filtered by trust
        assert result.total_filtered == 1
        assert len(result.passed) == 1

    def test_denial_reasons_populated(self, registry, trust):
        task = TaskDescriptor.create(
            "t14", ["build_ui"], ["task_spec"],
            risk_tier=RiskTier.MEDIUM,
        )
        result = filter_candidates(task, registry, trust)
        assert any("eng.junior" in r for r in result.denial_reasons)
