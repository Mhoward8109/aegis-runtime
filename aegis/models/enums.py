"""Canonical enums for Aegis Runtime Contracts v1.1.

These enums are the single source of truth for all controlled vocabulary
values used across agent specs, governance, state authority, and orchestration.
"""

from enum import Enum, unique


@unique
class AgentStatus(str, Enum):
    """Agent lifecycle status. Only ACTIVE agents are routable by default."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"
    SUSPENDED = "suspended"


@unique
class TrustTier(str, Enum):
    """Governance-owned trust classification.
    
    Determines admission stringency, tool access, and monitoring thresholds.
    Agents without a trust registry entry default to LOW.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@unique
class ConflictClass(str, Enum):
    """Context field conflict resolution strategy.
    
    Every context.updated event MUST declare its conflict class.
    Events without a conflict class are rejected by the sequencer.
    """
    REPLACEABLE = "replaceable"
    MERGEABLE = "mergeable"
    EXCLUSIVE = "exclusive"
    APPEND_ONLY = "append_only"


@unique
class SideEffectClass(str, Enum):
    """Rollback classification for orchestration steps with external effects."""
    NONE = "none"
    REVERSIBLE = "reversible"
    COMPENSATABLE = "compensatable"
    IRREVERSIBLE = "irreversible"


@unique
class RoutingMode(str, Enum):
    """How the router returns candidates to the orchestrator."""
    SINGLE = "single"
    RANKED = "ranked"
    ENSEMBLE = "ensemble"
    MANUAL_REVIEW = "manual_review"


@unique
class RiskTier(str, Enum):
    """Task risk classification for governance stringency."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@unique
class BudgetReservationState(str, Enum):
    """Budget reservation lifecycle states."""
    RESERVED = "reserved"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


@unique
class EvaluatorClass(str, Enum):
    """Available evaluator types for agent output validation."""
    SCHEMA = "schema"
    TOOL_RESULT = "tool_result"
    POLICY = "policy"
    BUDGET = "budget"
    HUMAN_GATE = "human_gate"
    QUALITY_HEURISTIC = "quality_heuristic"


@unique
class VersionBump(str, Enum):
    """Classification of spec change magnitude.
    
    Used by spec_diff to determine required version increment.
    """
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    NONE = "none"
