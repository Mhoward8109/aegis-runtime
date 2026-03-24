"""Router — Contract 2 §2.3-2.5.

Pure query-and-rank function. Side-effect-free.
The router reads from registries but never writes to them.

Pipeline:
  1. FILTER: hard gates (status, capabilities, inputs, tools, environment, admission)
  2. SCORE:  weighted ranking across 4 dimensions
  3. RANK:   sort by score, apply confidence threshold
  4. RETURN: primary + fallbacks + reasoning metadata

Returns RouteResult on success, RoutingFailure on failure.
Never raises exceptions for routing logic — structured failures only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from aegis.models.agent_spec import AgentSpec
from aegis.models.enums import AgentStatus, RiskTier, RoutingMode, TrustTier
from aegis.registry.agent_registry import AgentRegistry
from aegis.registry.trust_registry import TrustRegistry
from aegis.router.scoring import (
    ContextStore,
    ExperienceStore,
    NullContextStore,
    NullExperienceStore,
    compute_total_score,
    score_capability_match,
    score_context_relevance,
    score_cost_risk,
    score_historical_performance,
)
from aegis.router.task_descriptor import TaskDescriptor
from aegis.router.types import (
    RouteResult,
    RoutingFailure,
    RoutingFailureReason,
    RoutingReason,
    ScoredCandidate,
)


# ---------------------------------------------------------------------------
# Admission function type
# ---------------------------------------------------------------------------

# Admission check is a pluggable function so the router doesn't
# import or depend on the governance module directly.
# Signature: (task, agent, trust_tier) -> (admitted: bool, reason: str)
AdmissionCheck = Callable[[TaskDescriptor, AgentSpec, TrustTier], tuple[bool, str]]


def default_admission_check(
    task: TaskDescriptor,
    agent: AgentSpec,
    trust: TrustTier,
) -> tuple[bool, str]:
    """Default trust-vs-risk admission per Contract 5 §5.7.

    This is the simplified admission check. The full governor (P2)
    will replace this with budget, policy, and rate-limit checks.
    """
    risk_rank = {RiskTier.LOW: 0, RiskTier.MEDIUM: 1, RiskTier.HIGH: 2, RiskTier.CRITICAL: 3}
    trust_rank = {TrustTier.LOW: 0, TrustTier.MEDIUM: 1, TrustTier.HIGH: 2, TrustTier.CRITICAL: 3}

    if task.risk_tier == RiskTier.CRITICAL:
        return False, "Critical risk tasks require human approval"

    if trust_rank[trust] < risk_rank[task.risk_tier]:
        return False, (
            f"Trust tier {trust.value} insufficient for "
            f"risk tier {task.risk_tier.value}"
        )

    return True, "admitted"


# ---------------------------------------------------------------------------
# Filter phase
# ---------------------------------------------------------------------------


@dataclass
class FilterResult:
    """Output of filter phase."""
    passed: list[AgentSpec]
    total_evaluated: int
    total_filtered: int
    denial_reasons: list[str]


def filter_candidates(
    task: TaskDescriptor,
    registry: AgentRegistry,
    trust_registry: TrustRegistry,
    admission_check: AdmissionCheck = default_admission_check,
) -> FilterResult:
    """Contract 2 §2.3 step 1: FILTER phase.

    Hard gates — any failure = exclusion.
    1a. status == active
    1b. required_capabilities ⊆ agent.capabilities
    1c. inputs_available ⊇ agent.required_inputs
    1d. allowed_tools ⊇ agent.tools (if specified)
    1e. environment compatibility (simplified: runtime check)
    1f. admission check (trust vs risk)
    """
    # 1a + 1b: registry query handles status + capability filtering
    candidates = registry.query_by_capability(
        required=list(task.required_capabilities),
        status_filter=[AgentStatus.ACTIVE],
    )

    total_evaluated = len(candidates)
    passed: list[AgentSpec] = []
    denial_reasons: list[str] = []

    for agent in candidates:
        # 1c: required inputs check
        if not set(agent.required_inputs).issubset(set(task.inputs_available)):
            missing = set(agent.required_inputs) - set(task.inputs_available)
            denial_reasons.append(
                f"{agent.agent_id}: missing required inputs {sorted(missing)}"
            )
            continue

        # 1d: tool constraint check
        if task.constraints.allowed_tools is not None:
            disallowed = set(agent.tools) - set(task.constraints.allowed_tools)
            if disallowed:
                denial_reasons.append(
                    f"{agent.agent_id}: uses disallowed tools {sorted(disallowed)}"
                )
                continue

        # 1e: environment compatibility (basic runtime check)
        # Full environment compatibility is deferred to P2.
        # At P1, all runtimes are compatible.

        # 1f: admission check
        agent_trust = trust_registry.get_trust(agent.agent_id)
        admitted, reason = admission_check(task, agent, agent_trust)
        if not admitted:
            denial_reasons.append(f"{agent.agent_id}: {reason}")
            continue

        passed.append(agent)

    return FilterResult(
        passed=passed,
        total_evaluated=total_evaluated,
        total_filtered=total_evaluated - len(passed),
        denial_reasons=denial_reasons,
    )


# ---------------------------------------------------------------------------
# Router configuration
# ---------------------------------------------------------------------------


@dataclass
class RouterConfig:
    """Tunable router parameters."""
    minimum_confidence_threshold: float = 50.0
    max_fallbacks: int = 3


# ---------------------------------------------------------------------------
# Main router function
# ---------------------------------------------------------------------------


def route(
    task: TaskDescriptor,
    registry: AgentRegistry,
    trust_registry: TrustRegistry,
    *,
    experience_store: ExperienceStore | None = None,
    context_store: ContextStore | None = None,
    admission_check: AdmissionCheck = default_admission_check,
    config: RouterConfig | None = None,
    workflow_id: str | None = None,
) -> RouteResult | RoutingFailure:
    """Route a task to the best available agent.

    Contract 2 §2.3: FILTER → SCORE → RANK → RETURN.

    Pure function. Reads from registries, never writes.
    Returns structured result, never raises for routing logic.

    Args:
        task: Validated task descriptor.
        registry: Agent registry for candidate lookup.
        trust_registry: Trust registry for admission checks.
        experience_store: Historical performance data (P3, stubbed).
        context_store: Workflow context data (P2, stubbed).
        admission_check: Pluggable admission function. Default: trust-vs-risk.
        config: Router tuning parameters.
        workflow_id: Current workflow ID for context relevance scoring.

    Returns:
        RouteResult on success, RoutingFailure on failure.
    """
    if experience_store is None:
        experience_store = NullExperienceStore()
    if context_store is None:
        context_store = NullContextStore()
    if config is None:
        config = RouterConfig()

    # --- Step 1: FILTER ---
    filter_result = filter_candidates(
        task, registry, trust_registry, admission_check
    )

    if not filter_result.passed:
        # Determine failure reason
        if filter_result.total_evaluated == 0:
            return RoutingFailure(
                task_id=task.task_id,
                reason=RoutingFailureReason.NO_SUITABLE_AGENT,
                detail="No agents match required capabilities",
                missing_capabilities=task.required_capabilities,
            )

        if filter_result.denial_reasons:
            # Had candidates but all were filtered
            governance_denials = [
                r for r in filter_result.denial_reasons
                if "trust" in r.lower() or "admission" in r.lower()
                or "human approval" in r.lower()
            ]
            if governance_denials:
                return RoutingFailure(
                    task_id=task.task_id,
                    reason=RoutingFailureReason.BLOCKED_BY_GOVERNANCE,
                    detail="All candidates failed admission control",
                    denial_reasons=tuple(filter_result.denial_reasons),
                )

        return RoutingFailure(
            task_id=task.task_id,
            reason=RoutingFailureReason.ALL_CANDIDATES_FILTERED,
            detail=f"All {filter_result.total_evaluated} candidates filtered out",
            denial_reasons=tuple(filter_result.denial_reasons),
        )

    # --- Step 2: SCORE ---
    scored: list[ScoredCandidate] = []

    for agent in filter_result.passed:
        all_reasons: list[RoutingReason] = []

        all_reasons.extend(score_capability_match(task, agent))
        all_reasons.extend(score_context_relevance(
            task, agent, context_store, workflow_id
        ))
        all_reasons.extend(score_historical_performance(
            task, agent, experience_store
        ))
        all_reasons.extend(score_cost_risk(task, agent, experience_store))

        total = compute_total_score(all_reasons)

        scored.append(ScoredCandidate(
            agent_id=agent.agent_id,
            score=total,
            reasons=tuple(all_reasons),
        ))

    # --- Step 3: RANK ---
    scored.sort(key=lambda c: c.score, reverse=True)

    # Confidence threshold check
    if scored[0].score < config.minimum_confidence_threshold:
        return RoutingFailure(
            task_id=task.task_id,
            reason=RoutingFailureReason.BELOW_CONFIDENCE_THRESHOLD,
            detail=(
                f"Top score {scored[0].score:.1f} is below threshold "
                f"{config.minimum_confidence_threshold:.1f}"
            ),
        )

    # --- Step 4: RETURN ---
    # Tie-breaking: prefer lower execution time; if still tied, first in list
    # (which is the first returned by registry, effectively stable sort)
    primary = scored[0]
    fallbacks = tuple(scored[1:1 + config.max_fallbacks])

    return RouteResult(
        task_id=task.task_id,
        routing_mode=task.routing_mode,
        primary=primary,
        fallbacks=fallbacks,
        all_candidates=tuple(scored),
        candidates_evaluated=filter_result.total_evaluated,
        candidates_filtered=filter_result.total_filtered,
    )
