"""TaskDescriptor — Contract 2 §2.2.

Every routable task must conform to this structure. The task descriptor
is the router's input — it describes what needs to be done, what's
available, and what constraints apply.

Validation happens on construction. Invalid descriptors are rejected
before they reach the router.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aegis.models.enums import RiskTier, RoutingMode


@dataclass(frozen=True)
class TaskBudget:
    """Budget constraints for a single task."""
    max_tokens: int = 50_000
    max_cost_usd: float = 0.50
    max_duration_seconds: int = 120

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be positive")
        if self.max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds must be positive")


@dataclass(frozen=True)
class TaskOrigin:
    """Where the task came from."""
    source: str  # "user" | "orchestrator" | "agent"
    source_id: str = ""

    def __post_init__(self) -> None:
        valid_sources = {"user", "orchestrator", "agent"}
        if self.source not in valid_sources:
            raise ValueError(
                f"Invalid origin source '{self.source}'. "
                f"Must be one of: {valid_sources}"
            )


@dataclass(frozen=True)
class TaskConstraints:
    """Execution constraints imposed on the task."""
    require_sandbox: bool = True
    allowed_tools: tuple[str, ...] | None = None  # None = no tool restriction


@dataclass(frozen=True)
class TaskDescriptor:
    """Complete task descriptor per Contract 2 §2.2.

    Immutable after construction. Validated on creation.
    """
    task_id: str
    required_capabilities: tuple[str, ...]
    inputs_available: tuple[str, ...]

    # Optional with defaults
    preferred_capabilities: tuple[str, ...] = ()
    priority: str = "normal"  # "critical" | "high" | "normal" | "low"
    routing_mode: RoutingMode = RoutingMode.SINGLE
    risk_tier: RiskTier = RiskTier.LOW
    budget: TaskBudget = field(default_factory=TaskBudget)
    origin: TaskOrigin = field(default_factory=lambda: TaskOrigin(source="user"))
    constraints: TaskConstraints = field(default_factory=TaskConstraints)
    context_ref: str | None = None

    def __post_init__(self) -> None:
        errors = self._validate()
        if errors:
            raise ValueError(f"Invalid TaskDescriptor: {'; '.join(errors)}")

    def _validate(self) -> list[str]:
        errors: list[str] = []

        if not self.task_id:
            errors.append("task_id must not be empty")

        if not self.required_capabilities:
            errors.append("required_capabilities must have at least one entry")

        valid_priorities = {"critical", "high", "normal", "low"}
        if self.priority not in valid_priorities:
            errors.append(
                f"Invalid priority '{self.priority}'. "
                f"Must be one of: {valid_priorities}"
            )

        return errors

    @classmethod
    def create(
        cls,
        task_id: str,
        required_capabilities: list[str],
        inputs_available: list[str],
        **kwargs: Any,
    ) -> TaskDescriptor:
        """Convenience factory that accepts lists and converts to tuples."""
        preferred = kwargs.pop("preferred_capabilities", [])
        return cls(
            task_id=task_id,
            required_capabilities=tuple(required_capabilities),
            inputs_available=tuple(inputs_available),
            preferred_capabilities=tuple(preferred),
            **kwargs,
        )
