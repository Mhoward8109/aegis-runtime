"""Canonical test fixtures for Aegis conformance testing.

These fixtures provide reusable AgentSpec instances and raw dicts
for testing schema validation, registry operations, capability lookup,
trust management, and version enforcement.

Used by P0 tests and designed to be reused in P1+ router/governance tests.
"""

from __future__ import annotations

from aegis.models.agent_spec import (
    AgentSpec,
    EnvironmentConfig,
    EvaluationConfig,
    AgentMetadata,
    ChangelogEntry,
)
from aegis.models.enums import AgentStatus, EvaluatorClass


def valid_agent_spec() -> AgentSpec:
    """A well-formed, minimal-but-complete agent spec."""
    return AgentSpec(
        agent_id="engineering.frontend-developer",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Frontend Developer",
        capabilities=["build_ui", "optimize_rendering", "integrate_api"],
        required_inputs=["task_spec", "design_spec"],
        optional_inputs=["api_schema"],
        outputs=["ui_code", "component_structure"],
        output_schemas={},
        tools=["code_editor", "browser_test", "linter"],
        constraints=["must_follow_design_system", "no_inline_styles"],
        depends_on=[],
        required_inputs_from={},
        environment=EnvironmentConfig(
            runtime="node",
            sandbox_required=True,
            max_execution_seconds=120,
        ),
        evaluation=EvaluationConfig(
            success_criteria=["passes_lint", "responsive_layout", "no_console_errors"],
            evaluator_classes=[EvaluatorClass.SCHEMA, EvaluatorClass.POLICY],
            max_retries=2,
            circuit_breaker_on=["invalid_output_schema", "policy_violation"],
        ),
        metadata=AgentMetadata(
            author="aegis-team",
            created="2026-03-19",
            changelog=[
                ChangelogEntry(version="1.0.0", date="2026-03-19", note="Initial release"),
            ],
        ),
    )


def valid_agent_spec_dict() -> dict:
    """Raw dict form of a valid agent spec — for testing from_dict parsing."""
    return {
        "agent_id": "engineering.frontend-developer",
        "version": "1.0.0",
        "status": "active",
        "role": "Frontend Developer",
        "capabilities": ["build_ui", "optimize_rendering", "integrate_api"],
        "required_inputs": ["task_spec", "design_spec"],
        "optional_inputs": ["api_schema"],
        "outputs": ["ui_code", "component_structure"],
        "output_schemas": {},
        "tools": ["code_editor", "browser_test", "linter"],
        "constraints": ["must_follow_design_system", "no_inline_styles"],
        "depends_on": [],
        "required_inputs_from": {},
        "environment": {
            "runtime": "node",
            "sandbox_required": True,
            "max_execution_seconds": 120,
        },
        "evaluation": {
            "success_criteria": ["passes_lint", "responsive_layout", "no_console_errors"],
            "evaluator_classes": ["schema", "policy"],
            "max_retries": 2,
            "circuit_breaker_on": ["invalid_output_schema", "policy_violation"],
        },
    }


def valid_backend_agent_spec() -> AgentSpec:
    """A second valid agent for multi-agent registry tests."""
    return AgentSpec(
        agent_id="engineering.backend-architect",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Backend Architect",
        capabilities=["write_backend", "design_schema", "integrate_api"],
        required_inputs=["task_spec"],
        optional_inputs=["api_schema", "design_spec"],
        outputs=["backend_code", "api_schema"],
        tools=["code_editor", "linter"],
        constraints=["must_use_type_hints"],
        evaluation=EvaluationConfig(
            success_criteria=["passes_lint", "type_check_clean"],
        ),
    )


def valid_research_agent_spec() -> AgentSpec:
    """A research agent for capability query tests."""
    return AgentSpec(
        agent_id="product.trend-researcher",
        version="1.0.0",
        status=AgentStatus.ACTIVE,
        role="Trend Researcher",
        capabilities=["synthesize_research", "analyze_data"],
        required_inputs=["task_spec"],
        outputs=["research_report"],
        tools=[],
        constraints=[],
        evaluation=EvaluationConfig(
            success_criteria=["report_complete"],
        ),
    )


def deprecated_agent_spec() -> AgentSpec:
    """A deprecated agent — discoverable but not routable."""
    return AgentSpec(
        agent_id="legacy.old-formatter",
        version="2.0.0",
        status=AgentStatus.DEPRECATED,
        role="Legacy Formatter",
        capabilities=["generate_report"],
        required_inputs=["raw_data"],
        outputs=["formatted_report"],
        tools=["code_editor"],
        constraints=[],
        evaluation=EvaluationConfig(
            success_criteria=["output_valid"],
        ),
    )


def suspended_agent_spec() -> AgentSpec:
    """A suspended agent — invisible to router and queries."""
    return AgentSpec(
        agent_id="testing.broken-tester",
        version="1.0.0",
        status=AgentStatus.SUSPENDED,
        role="Broken Tester",
        capabilities=["write_tests"],
        required_inputs=["code"],
        outputs=["test_results"],
        tools=["code_editor"],
        constraints=[],
        evaluation=EvaluationConfig(
            success_criteria=["tests_pass"],
        ),
    )


def experimental_agent_spec() -> AgentSpec:
    """An experimental agent — routable but with governance restrictions."""
    return AgentSpec(
        agent_id="ai.code-reviewer",
        version="0.1.0",
        status=AgentStatus.EXPERIMENTAL,
        role="AI Code Reviewer",
        capabilities=["review_code", "debug_issue"],
        required_inputs=["code", "task_spec"],
        outputs=["review_report"],
        tools=["code_editor", "linter"],
        constraints=["read_only_access"],
        evaluation=EvaluationConfig(
            success_criteria=["review_complete", "no_false_positives"],
            max_retries=1,
        ),
    )


# --- Invalid specs for negative testing ---


def invalid_agent_id_dict() -> dict:
    """Invalid agent_id — missing domain separator."""
    d = valid_agent_spec_dict()
    d["agent_id"] = "frontenddev"  # no dot separator
    return d


def invalid_agent_id_uppercase_dict() -> dict:
    """Invalid agent_id — uppercase characters."""
    d = valid_agent_spec_dict()
    d["agent_id"] = "Engineering.Frontend"
    return d


def invalid_semver_dict() -> dict:
    """Invalid version string."""
    d = valid_agent_spec_dict()
    d["version"] = "v1.0"  # not X.Y.Z
    return d


def invalid_status_dict() -> dict:
    """Invalid status enum value."""
    d = valid_agent_spec_dict()
    d["status"] = "inactive"  # not in enum
    return d


def empty_capabilities_dict() -> dict:
    """Empty capabilities array — must have at least one."""
    d = valid_agent_spec_dict()
    d["capabilities"] = []
    return d


def unknown_capability_dict() -> dict:
    """Capabilities not in controlled vocabulary."""
    d = valid_agent_spec_dict()
    d["capabilities"] = ["build_ui", "teleport_users"]  # teleport_users is not real
    return d


def broken_output_schema_ref_dict() -> dict:
    """Output schema reference that won't resolve to a file."""
    d = valid_agent_spec_dict()
    d["output_schemas"] = {"ui_code": "schemas/nonexistent_v99.json"}
    return d


def self_dependent_dict() -> dict:
    """Agent that depends on itself."""
    d = valid_agent_spec_dict()
    d["depends_on"] = ["engineering.frontend-developer"]
    return d
