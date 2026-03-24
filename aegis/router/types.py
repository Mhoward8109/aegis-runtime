"""Router types — Contract 2 §2.3, §2.5.

Structured result objects for routing outcomes. These are the router's
public interface — everything downstream (orchestrator, governor, audit log)
consumes these types.

The router never raises exceptions for routing failures. It returns
structured RoutingFailure objects instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, unique

from aegis.models.enums import RoutingMode


@unique
class RoutingFailureReason(str, Enum):
    """Why a routing attempt failed."""
    NO_SUITABLE_AGENT = "no_suitable_agent"
    BLOCKED_BY_GOVERNANCE = "blocked_by_governance"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    BELOW_CONFIDENCE_THRESHOLD = "below_confidence_threshold"
    ALL_CANDIDATES_FILTERED = "all_candidates_filtered"
    EMPTY_REQUIRED_CAPABILITIES = "empty_required_capabilities"


@dataclass(frozen=True)
class RoutingReason:
    """Single scoring justification for audit trail."""
    factor: str        # e.g. "preferred_capability", "specialization", "cost_risk"
    delta: float       # score change (positive or negative)
    detail: str        # human-readable explanation


@dataclass(frozen=True)
class ScoredCandidate:
    """An agent scored and ranked by the router."""
    agent_id: str
    score: float
    reasons: tuple[RoutingReason, ...]

    @property
    def reason_summary(self) -> str:
        parts = [f"{r.factor}: {r.delta:+.1f}" for r in self.reasons]
        return ", ".join(parts) if parts else "baseline"


@dataclass(frozen=True)
class RouteResult:
    """Successful routing outcome."""
    task_id: str
    routing_mode: RoutingMode
    primary: ScoredCandidate
    fallbacks: tuple[ScoredCandidate, ...]
    all_candidates: tuple[ScoredCandidate, ...]  # full ranked list for audit
    candidates_evaluated: int
    candidates_filtered: int

    @property
    def primary_agent_id(self) -> str:
        return self.primary.agent_id


@dataclass(frozen=True)
class RoutingFailure:
    """Structured routing failure — not an exception."""
    task_id: str
    reason: RoutingFailureReason
    detail: str
    missing_capabilities: tuple[str, ...] = ()
    denial_reasons: tuple[str, ...] = ()
