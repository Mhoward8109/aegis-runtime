"""Capability Vocabulary — Contract 1 §1.3.

Maintains the canonical list of capability tags. The registry rejects
agent specs with capabilities not in this vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Starter set from Appendix A
_DEFAULT_CAPABILITIES: set[str] = {
    "build_ui",
    "optimize_rendering",
    "integrate_api",
    "write_backend",
    "design_schema",
    "analyze_data",
    "synthesize_research",
    "generate_report",
    "write_tests",
    "review_code",
    "debug_issue",
    "deploy_service",
    "assess_risk",
    "audit_compliance",
    "monitor_security",
    "plan_sprint",
    "prioritize_backlog",
    "estimate_effort",
}


@dataclass
class ValidationResult:
    """Result of vocabulary validation."""
    valid: bool
    unknown_capabilities: list[str] = field(default_factory=list)


class CapabilityVocabulary:
    """Controlled vocabulary for agent capability tags.

    All capabilities must be registered before they can be used in agent specs.
    The vocabulary is initialized with the starter set from Appendix A
    and can be extended at runtime.
    """

    def __init__(self, initial: set[str] | None = None) -> None:
        self._capabilities: set[str] = set(initial or _DEFAULT_CAPABILITIES)

    def validate(self, capabilities: list[str]) -> ValidationResult:
        """Check all capabilities are in controlled vocabulary.

        Returns ValidationResult with list of unknown capabilities if any.
        """
        unknown = [cap for cap in capabilities if cap not in self._capabilities]
        return ValidationResult(
            valid=len(unknown) == 0,
            unknown_capabilities=unknown,
        )

    def register_capability(self, capability: str) -> bool:
        """Add new capability to vocabulary. Idempotent.

        Returns True if newly added, False if already existed.
        """
        if capability in self._capabilities:
            return False
        self._capabilities.add(capability)
        return True

    def list_capabilities(self) -> list[str]:
        """Return all registered capabilities, sorted."""
        return sorted(self._capabilities)

    def __contains__(self, capability: str) -> bool:
        return capability in self._capabilities

    def __len__(self) -> int:
        return len(self._capabilities)
