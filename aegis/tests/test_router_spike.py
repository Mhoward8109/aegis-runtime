"""Router Integration Spike — P0 → P1 Handoff Proof.

This is NOT the router. This is a spike that proves the P0 registry
interfaces are sufficient to build the P1 router without adapter code.

Four claims to prove:
1. query_by_capability returns router-usable candidates without adapter glue
2. trust lookup cleanly feeds admission logic
3. status filtering behaves correctly across all agent states
4. registry outputs are stable enough for P1 scoring inputs

If this file runs green, P0 is doing its job.
If it needs adapters, P0 needs cleanup before P1.
"""

import pytest
from dataclasses import dataclass

from aegis.models import (
    AgentSpec,
    AgentStatus,
    EvaluationConfig,
    TrustTier,
    RiskTier,
)
from aegis.registry import (
    AgentRegistry,
    CapabilityVocabulary,
    SchemaValidator,
    TrustRegistry,
)


# ---------------------------------------------------------------------------
# Minimal router prototype — just enough to prove interface compatibility
# ---------------------------------------------------------------------------


@dataclass
class TaskDescriptor:
    """Minimal task descriptor per Contract 2 §2.2."""
    task_id: str
    required_capabilities: list[str]
    preferred_capabilities: list[str]
    inputs_available: list[str]
    risk_tier: RiskTier = RiskTier.LOW


@dataclass
class ScoredCandidate:
    """Router output: agent + score + reasoning."""
    agent_id: str
    score: float
    reasons: list[str]


def filter_candidates(
    task: TaskDescriptor,
    registry: AgentRegistry,
    trust: TrustRegistry,
) -> list[AgentSpec]:
    """Router filter phase — Contract 2 §2.3, steps 1a-1f.

    Uses P0 interfaces directly. No adapters.
    """
    # Step 1b: capability filter (1a status filter is built into query)
    candidates = registry.query_by_capability(
        required=task.required_capabilities,
        status_filter=[AgentStatus.ACTIVE],
    )

    filtered: list[AgentSpec] = []
    for agent in candidates:
        # Step 1c: required inputs must be satisfiable
        if not set(agent.required_inputs).issubset(set(task.inputs_available)):
            continue

        # Step 1f: trust-based admission (simplified)
        agent_trust = trust.get_trust(agent.agent_id)
        if not _trust_admits(task.risk_tier, agent_trust):
            continue

        filtered.append(agent)

    return filtered


def score_candidates(
    task: TaskDescriptor,
    candidates: list[AgentSpec],
) -> list[ScoredCandidate]:
    """Router score phase — Contract 2 §2.3, step 2.

    Proves that AgentSpec fields are directly usable for scoring
    without transformation or adapter logic.
    """
    scored: list[ScoredCandidate] = []

    for agent in candidates:
        score = 0.0
        reasons: list[str] = []

        # 2a: preferred capability match
        preferred_matches = set(task.preferred_capabilities) & set(agent.capabilities)
        cap_score = len(preferred_matches) * 25
        score += cap_score
        if preferred_matches:
            reasons.append(f"+{cap_score} preferred capabilities: {preferred_matches}")

        # 2a: specialization bonus
        if agent.capabilities:
            task_caps = set(task.required_capabilities) | set(task.preferred_capabilities)
            overlap = len(set(agent.capabilities) & task_caps) / len(agent.capabilities)
            if overlap > 0.7:
                score += 15
                reasons.append(f"+15 specialization bonus (overlap={overlap:.2f})")

        # 2d: cost risk (use environment timeout as proxy for cost)
        if agent.environment.max_execution_seconds > 600:
            score -= 20
            reasons.append("-20 high execution time risk")

        scored.append(ScoredCandidate(
            agent_id=agent.agent_id,
            score=score,
            reasons=reasons,
        ))

    # Sort descending
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored


def _trust_admits(risk: RiskTier, trust: TrustTier) -> bool:
    """Simplified admission check — Contract 5 §5.7.

    Proves trust registry output feeds admission logic directly.
    """
    risk_rank = {RiskTier.LOW: 0, RiskTier.MEDIUM: 1, RiskTier.HIGH: 2, RiskTier.CRITICAL: 3}
    trust_rank = {TrustTier.LOW: 0, TrustTier.MEDIUM: 1, TrustTier.HIGH: 2, TrustTier.CRITICAL: 3}

    # Low risk: any trust level
    # Medium risk: trust >= medium
    # High risk: trust >= high
    # Critical: always requires human (not modeled here, just deny)
    if risk == RiskTier.CRITICAL:
        return False
    return trust_rank[trust] >= risk_rank[risk]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vocab() -> CapabilityVocabulary:
    return CapabilityVocabulary()


@pytest.fixture
def trust() -> TrustRegistry:
    t = TrustRegistry()
    t.set_trust("engineering.frontend-dev", TrustTier.MEDIUM, "operator")
    t.set_trust("engineering.backend-dev", TrustTier.HIGH, "operator")
    t.set_trust("engineering.junior-dev", TrustTier.LOW, "operator")
    # product.researcher has no entry → defaults to LOW
    return t


@pytest.fixture
def registry(vocab: CapabilityVocabulary) -> AgentRegistry:
    validator = SchemaValidator(vocab)
    reg = AgentRegistry(validator, vocab)

    reg.register(AgentSpec(
        agent_id="engineering.frontend-dev",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Frontend Dev",
        capabilities=["build_ui", "integrate_api"],
        required_inputs=["task_spec"],
        optional_inputs=["design_spec"],
        outputs=["ui_code"],
        tools=["code_editor"],
        constraints=[],
        evaluation=EvaluationConfig(success_criteria=["lint_pass"]),
    ))

    reg.register(AgentSpec(
        agent_id="engineering.backend-dev",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Backend Dev",
        capabilities=["write_backend", "integrate_api", "design_schema"],
        required_inputs=["task_spec", "api_schema"],
        optional_inputs=[],
        outputs=["backend_code"],
        tools=["code_editor", "linter"],
        constraints=[],
        evaluation=EvaluationConfig(success_criteria=["lint_pass"]),
    ))

    reg.register(AgentSpec(
        agent_id="engineering.junior-dev",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Junior Dev",
        capabilities=["build_ui"],
        required_inputs=["task_spec"],
        optional_inputs=[],
        outputs=["ui_code"],
        tools=["code_editor"],
        constraints=["must_be_reviewed"],
        evaluation=EvaluationConfig(success_criteria=["lint_pass"]),
    ))

    reg.register(AgentSpec(
        agent_id="product.researcher",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Researcher",
        capabilities=["synthesize_research"],
        required_inputs=["task_spec"],
        outputs=["research_report"],
        tools=[],
        constraints=[],
        evaluation=EvaluationConfig(success_criteria=["report_complete"]),
    ))

    reg.register(AgentSpec(
        agent_id="legacy.old-builder",
        version="1.0.0",
        status=AgentStatus.DEPRECATED,
        role="Old Builder",
        capabilities=["build_ui"],
        required_inputs=["task_spec"],
        outputs=["ui_code"],
        tools=["code_editor"],
        constraints=[],
        evaluation=EvaluationConfig(success_criteria=["lint_pass"]),
    ))

    return reg


# ---------------------------------------------------------------------------
# Claim 1: query_by_capability returns router-usable candidates
#           without adapter glue
# ---------------------------------------------------------------------------


class TestClaim1_CapabilityQueryFeedsRouter:
    """The router filter phase can use query_by_capability output directly."""

    def test_single_capability_returns_scoreable_specs(self, registry, trust):
        task = TaskDescriptor(
            task_id="t1",
            required_capabilities=["build_ui"],
            preferred_capabilities=["integrate_api"],
            inputs_available=["task_spec"],
        )
        candidates = filter_candidates(task, registry, trust)
        scored = score_candidates(task, candidates)

        # Should get results — no adapter needed between registry and scoring
        assert len(scored) > 0
        # Each result has the fields scoring needs
        for s in scored:
            assert isinstance(s.agent_id, str)
            assert isinstance(s.score, float)

    def test_multi_capability_intersection_works(self, registry, trust):
        task = TaskDescriptor(
            task_id="t2",
            required_capabilities=["integrate_api", "build_ui"],
            preferred_capabilities=[],
            inputs_available=["task_spec"],
        )
        candidates = filter_candidates(task, registry, trust)

        # Only frontend-dev has both capabilities
        assert len(candidates) == 1
        assert candidates[0].agent_id == "engineering.frontend-dev"

    def test_required_inputs_filter_works_directly(self, registry, trust):
        task = TaskDescriptor(
            task_id="t3",
            required_capabilities=["integrate_api"],
            preferred_capabilities=[],
            inputs_available=["task_spec"],  # missing api_schema
        )
        candidates = filter_candidates(task, registry, trust)

        # backend-dev requires api_schema which isn't available
        ids = {c.agent_id for c in candidates}
        assert "engineering.backend-dev" not in ids
        # frontend-dev only requires task_spec
        assert "engineering.frontend-dev" in ids

    def test_agent_spec_fields_accessible_without_transformation(self, registry):
        agents = registry.query_by_capability(["build_ui"])
        for agent in agents:
            # All fields the router needs are directly accessible
            assert hasattr(agent, "agent_id")
            assert hasattr(agent, "capabilities")
            assert hasattr(agent, "required_inputs")
            assert hasattr(agent, "optional_inputs")
            assert hasattr(agent, "tools")
            assert hasattr(agent, "environment")
            assert hasattr(agent, "evaluation")
            # Types are correct — no string parsing needed
            assert isinstance(agent.capabilities, list)
            assert isinstance(agent.required_inputs, list)
            assert isinstance(agent.environment.max_execution_seconds, int)
            assert isinstance(agent.evaluation.max_retries, int)


# ---------------------------------------------------------------------------
# Claim 2: trust lookup cleanly feeds admission logic
# ---------------------------------------------------------------------------


class TestClaim2_TrustFeedsAdmission:
    """Trust registry output plugs directly into admission decisions."""

    def test_low_risk_admits_low_trust(self, registry, trust):
        task = TaskDescriptor(
            task_id="t4",
            required_capabilities=["build_ui"],
            preferred_capabilities=[],
            inputs_available=["task_spec"],
            risk_tier=RiskTier.LOW,
        )
        candidates = filter_candidates(task, registry, trust)
        ids = {c.agent_id for c in candidates}

        # junior-dev has LOW trust, LOW risk task → admitted
        assert "engineering.junior-dev" in ids

    def test_medium_risk_blocks_low_trust(self, registry, trust):
        task = TaskDescriptor(
            task_id="t5",
            required_capabilities=["build_ui"],
            preferred_capabilities=[],
            inputs_available=["task_spec"],
            risk_tier=RiskTier.MEDIUM,
        )
        candidates = filter_candidates(task, registry, trust)
        ids = {c.agent_id for c in candidates}

        # junior-dev has LOW trust, MEDIUM risk → blocked
        assert "engineering.junior-dev" not in ids
        # frontend-dev has MEDIUM trust → admitted
        assert "engineering.frontend-dev" in ids

    def test_high_risk_requires_high_trust(self, registry, trust):
        task = TaskDescriptor(
            task_id="t6",
            required_capabilities=["integrate_api"],
            preferred_capabilities=[],
            inputs_available=["task_spec", "api_schema"],
            risk_tier=RiskTier.HIGH,
        )
        candidates = filter_candidates(task, registry, trust)
        ids = {c.agent_id for c in candidates}

        # frontend-dev has MEDIUM trust, HIGH risk → blocked
        assert "engineering.frontend-dev" not in ids
        # backend-dev has HIGH trust → admitted
        assert "engineering.backend-dev" in ids

    def test_unknown_agent_defaults_low_trust(self, trust):
        # researcher has no trust entry
        tier = trust.get_trust("product.researcher")
        assert tier == TrustTier.LOW
        # No adapter needed — enum comparison works directly
        assert _trust_admits(RiskTier.LOW, tier) is True
        assert _trust_admits(RiskTier.MEDIUM, tier) is False

    def test_trust_tier_is_enum_not_string(self, trust):
        """Trust returns an enum, not a string. Router doesn't need to parse."""
        tier = trust.get_trust("engineering.frontend-dev")
        assert isinstance(tier, TrustTier)
        assert tier == TrustTier.MEDIUM
        # Direct comparison works
        assert tier != TrustTier.LOW


# ---------------------------------------------------------------------------
# Claim 3: status filtering behaves correctly across all agent states
# ---------------------------------------------------------------------------


class TestClaim3_StatusFiltering:
    """Status filtering works without router-side logic."""

    def test_deprecated_excluded_from_default_query(self, registry):
        results = registry.query_by_capability(["build_ui"])
        ids = {r.agent_id for r in results}
        assert "legacy.old-builder" not in ids

    def test_deprecated_findable_when_explicitly_requested(self, registry):
        results = registry.query_by_capability(
            ["build_ui"],
            status_filter=[AgentStatus.ACTIVE, AgentStatus.DEPRECATED],
        )
        ids = {r.agent_id for r in results}
        assert "legacy.old-builder" in ids

    def test_suspended_invisible_even_when_requested(self, registry):
        # Register a suspended agent
        registry.register(AgentSpec(
            agent_id="testing.broken",
            version="1.0.0",
            status=AgentStatus.SUSPENDED,
            role="Broken",
            capabilities=["write_tests"],
            required_inputs=["code"],
            outputs=["test_results"],
            tools=[],
            constraints=[],
            evaluation=EvaluationConfig(success_criteria=["pass"]),
        ))

        # Suspended agents should only appear if explicitly filtered for
        results = registry.query_by_capability(["write_tests"])
        assert len(results) == 0

        results = registry.query_by_capability(
            ["write_tests"],
            status_filter=[AgentStatus.SUSPENDED],
        )
        assert len(results) == 1

    def test_status_is_enum_on_returned_specs(self, registry):
        """Router gets enum, not string. No parsing needed."""
        results = registry.query_by_capability(["build_ui"])
        for agent in results:
            assert isinstance(agent.status, AgentStatus)
            assert agent.status == AgentStatus.ACTIVE


# ---------------------------------------------------------------------------
# Claim 4: registry outputs are stable enough for P1 scoring inputs
# ---------------------------------------------------------------------------


class TestClaim4_StableScoringInputs:
    """Scoring can consume registry output without field mapping or transforms."""

    def test_scoring_produces_ranked_list(self, registry, trust):
        task = TaskDescriptor(
            task_id="t7",
            required_capabilities=["build_ui"],
            preferred_capabilities=["integrate_api"],
            inputs_available=["task_spec"],
            risk_tier=RiskTier.LOW,
        )
        candidates = filter_candidates(task, registry, trust)
        scored = score_candidates(task, candidates)

        assert len(scored) >= 2
        # frontend-dev should score higher (has preferred integrate_api)
        assert scored[0].agent_id == "engineering.frontend-dev"
        assert scored[0].score > scored[1].score

    def test_specialization_bonus_applied(self, registry, trust):
        task = TaskDescriptor(
            task_id="t8",
            required_capabilities=["build_ui"],
            preferred_capabilities=["integrate_api"],
            inputs_available=["task_spec"],
            risk_tier=RiskTier.LOW,
        )
        candidates = filter_candidates(task, registry, trust)
        scored = score_candidates(task, candidates)

        # frontend-dev: 2 caps, both relevant → overlap = 1.0 → bonus
        frontend = next(s for s in scored if s.agent_id == "engineering.frontend-dev")
        assert any("specialization" in r for r in frontend.reasons)

    def test_scoring_handles_zero_preferred(self, registry, trust):
        task = TaskDescriptor(
            task_id="t9",
            required_capabilities=["synthesize_research"],
            preferred_capabilities=[],
            inputs_available=["task_spec"],
            risk_tier=RiskTier.LOW,
        )
        candidates = filter_candidates(task, registry, trust)
        scored = score_candidates(task, candidates)

        assert len(scored) == 1
        assert scored[0].agent_id == "product.researcher"

    def test_evaluation_config_accessible_for_retry_planning(self, registry):
        """Orchestrator needs max_retries and circuit_breaker_on from specs."""
        agents = registry.query_by_capability(["build_ui"])
        for agent in agents:
            assert isinstance(agent.evaluation.max_retries, int)
            assert isinstance(agent.evaluation.circuit_breaker_on, list)
            # Directly usable for retry logic
            assert agent.evaluation.max_retries >= 0
            assert agent.evaluation.max_retries <= 5

    def test_environment_config_accessible_for_sandbox_decisions(self, registry):
        """Governor needs sandbox_required and timeout from specs."""
        agents = registry.query_by_capability(["build_ui"])
        for agent in agents:
            assert isinstance(agent.environment.sandbox_required, bool)
            assert isinstance(agent.environment.max_execution_seconds, int)
            # Directly usable for admission/monitor decisions
            assert agent.environment.max_execution_seconds > 0

    def test_tools_list_accessible_for_permission_check(self, registry):
        """Governor needs tools list for allowed_tools ⊆ agent.tools check."""
        agents = registry.query_by_capability(["build_ui"])
        for agent in agents:
            assert isinstance(agent.tools, list)
            # All entries are strings, directly comparable
            for tool in agent.tools:
                assert isinstance(tool, str)
