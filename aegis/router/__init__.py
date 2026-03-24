"""Aegis Router — P1 runtime infrastructure.

Pure query-and-rank routing. No side effects. No orchestration logic.
"""

from aegis.router.router import (
    AdmissionCheck,
    FilterResult,
    RouterConfig,
    default_admission_check,
    filter_candidates,
    route,
)
from aegis.router.scoring import (
    ContextStore,
    ExperienceStore,
    NullContextStore,
    NullExperienceStore,
    compute_total_score,
    score_capability_match,
    score_context_relevance,
    score_cost_risk,
    score_exploration_bonus,
    score_historical_performance,
)
from aegis.router.task_descriptor import (
    TaskBudget,
    TaskConstraints,
    TaskDescriptor,
    TaskOrigin,
)
from aegis.router.types import (
    RouteResult,
    RoutingFailure,
    RoutingFailureReason,
    RoutingReason,
    ScoredCandidate,
)

__all__ = [
    "AdmissionCheck",
    "ContextStore",
    "ExperienceStore",
    "FilterResult",
    "NullContextStore",
    "NullExperienceStore",
    "RouteResult",
    "RouterConfig",
    "RoutingFailure",
    "RoutingFailureReason",
    "RoutingReason",
    "ScoredCandidate",
    "TaskBudget",
    "TaskConstraints",
    "TaskDescriptor",
    "TaskOrigin",
    "compute_total_score",
    "default_admission_check",
    "filter_candidates",
    "route",
    "score_capability_match",
    "score_context_relevance",
    "score_cost_risk",
    "score_historical_performance",
]
