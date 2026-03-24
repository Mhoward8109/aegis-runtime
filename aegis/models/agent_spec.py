"""AgentSpec model — Contract 1 §1.2.

Defines the structure every agent must conform to in order to be
registered, discovered, routed to, evaluated, and governed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from aegis.models.enums import AgentStatus, EvaluatorClass


# Validation patterns
AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass
class EnvironmentConfig:
    """Per-agent execution environment constraints."""
    runtime: str = "any"  # python | node | shell | any
    sandbox_required: bool = True
    max_execution_seconds: int = 300

    def __post_init__(self) -> None:
        valid_runtimes = {"python", "node", "shell", "any"}
        if self.runtime not in valid_runtimes:
            raise ValueError(
                f"Invalid runtime '{self.runtime}'. Must be one of: {valid_runtimes}"
            )
        if self.max_execution_seconds <= 0:
            raise ValueError("max_execution_seconds must be positive")


@dataclass
class EvaluationConfig:
    """Evaluation rules for agent output validation."""
    success_criteria: list[str] = field(default_factory=list)
    evaluator_classes: list[EvaluatorClass] = field(
        default_factory=lambda: [EvaluatorClass.SCHEMA, EvaluatorClass.POLICY]
    )
    max_retries: int = 2
    circuit_breaker_on: list[str] = field(
        default_factory=lambda: ["invalid_output_schema", "policy_violation"]
    )

    def __post_init__(self) -> None:
        if not self.success_criteria:
            raise ValueError("success_criteria must have at least one entry")
        if self.max_retries < 0 or self.max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")


@dataclass
class ChangelogEntry:
    """Single entry in agent spec changelog."""
    version: str
    date: str
    note: str


@dataclass
class AgentMetadata:
    """Optional metadata for agent specs."""
    author: str = ""
    created: str = ""
    changelog: list[ChangelogEntry] = field(default_factory=list)


@dataclass
class AgentSpec:
    """Complete agent specification per Contract 1 §1.2.

    This is the canonical representation of an agent in the Aegis runtime.
    All fields marked as required must be present for registration.
    """

    # Required fields
    agent_id: str
    version: str
    status: AgentStatus
    role: str
    capabilities: list[str]
    required_inputs: list[str]
    outputs: list[str]
    tools: list[str]
    constraints: list[str]
    evaluation: EvaluationConfig

    # Optional fields with defaults
    optional_inputs: list[str] = field(default_factory=list)
    output_schemas: dict[str, str] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    required_inputs_from: dict[str, str] = field(default_factory=dict)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    metadata: AgentMetadata | None = None

    def __post_init__(self) -> None:
        """Validate structural constraints on construction."""
        errors = self.validate()
        if errors:
            raise ValueError(
                f"Invalid AgentSpec: {'; '.join(errors)}"
            )

    def validate(self) -> list[str]:
        """Return list of validation errors. Empty list = valid."""
        errors: list[str] = []

        # agent_id pattern
        if not AGENT_ID_PATTERN.match(self.agent_id):
            errors.append(
                f"agent_id '{self.agent_id}' must match pattern 'domain.agent-name' "
                f"(lowercase alphanumeric + hyphens)"
            )

        # semver
        if not SEMVER_PATTERN.match(self.version):
            errors.append(
                f"version '{self.version}' must be valid semver (X.Y.Z)"
            )

        # capabilities non-empty
        if not self.capabilities:
            errors.append("capabilities must have at least one entry")

        # status enum
        if not isinstance(self.status, AgentStatus):
            try:
                AgentStatus(self.status)
            except ValueError:
                errors.append(
                    f"status '{self.status}' must be one of: "
                    f"{[s.value for s in AgentStatus]}"
                )

        # output_schemas keys must be subset of outputs
        unknown_schema_outputs = set(self.output_schemas.keys()) - set(self.outputs)
        if unknown_schema_outputs:
            errors.append(
                f"output_schemas references unknown outputs: {unknown_schema_outputs}"
            )

        # required_inputs_from keys must be subset of required_inputs + optional_inputs
        all_inputs = set(self.required_inputs) | set(self.optional_inputs)
        unknown_input_sources = set(self.required_inputs_from.keys()) - all_inputs
        if unknown_input_sources:
            errors.append(
                f"required_inputs_from references unknown inputs: {unknown_input_sources}"
            )

        return errors

    @property
    def domain(self) -> str:
        """Extract domain namespace from agent_id."""
        return self.agent_id.split(".")[0] if "." in self.agent_id else ""

    @property
    def name(self) -> str:
        """Extract agent name from agent_id."""
        parts = self.agent_id.split(".", 1)
        return parts[1] if len(parts) > 1 else self.agent_id

    @property
    def version_tuple(self) -> tuple[int, int, int]:
        """Parse version into (major, minor, patch) tuple."""
        parts = self.version.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for storage/transport."""
        result: dict[str, Any] = {
            "agent_id": self.agent_id,
            "version": self.version,
            "status": self.status.value if isinstance(self.status, AgentStatus) else self.status,
            "role": self.role,
            "capabilities": list(self.capabilities),
            "required_inputs": list(self.required_inputs),
            "optional_inputs": list(self.optional_inputs),
            "outputs": list(self.outputs),
            "output_schemas": dict(self.output_schemas),
            "tools": list(self.tools),
            "constraints": list(self.constraints),
            "depends_on": list(self.depends_on),
            "required_inputs_from": dict(self.required_inputs_from),
            "environment": {
                "runtime": self.environment.runtime,
                "sandbox_required": self.environment.sandbox_required,
                "max_execution_seconds": self.environment.max_execution_seconds,
            },
            "evaluation": {
                "success_criteria": list(self.evaluation.success_criteria),
                "evaluator_classes": [
                    ec.value if isinstance(ec, EvaluatorClass) else ec
                    for ec in self.evaluation.evaluator_classes
                ],
                "max_retries": self.evaluation.max_retries,
                "circuit_breaker_on": list(self.evaluation.circuit_breaker_on),
            },
        }
        if self.metadata:
            result["metadata"] = {
                "author": self.metadata.author,
                "created": self.metadata.created,
                "changelog": [
                    {"version": e.version, "date": e.date, "note": e.note}
                    for e in self.metadata.changelog
                ],
            }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSpec:
        """Deserialize from dictionary."""
        env_data = data.get("environment", {})
        eval_data = data.get("evaluation", {})
        meta_data = data.get("metadata")

        environment = EnvironmentConfig(
            runtime=env_data.get("runtime", "any"),
            sandbox_required=env_data.get("sandbox_required", True),
            max_execution_seconds=env_data.get("max_execution_seconds", 300),
        )

        evaluation = EvaluationConfig(
            success_criteria=eval_data.get("success_criteria", []),
            evaluator_classes=[
                EvaluatorClass(ec) if isinstance(ec, str) else ec
                for ec in eval_data.get("evaluator_classes", ["schema", "policy"])
            ],
            max_retries=eval_data.get("max_retries", 2),
            circuit_breaker_on=eval_data.get(
                "circuit_breaker_on", ["invalid_output_schema", "policy_violation"]
            ),
        )

        metadata = None
        if meta_data:
            metadata = AgentMetadata(
                author=meta_data.get("author", ""),
                created=meta_data.get("created", ""),
                changelog=[
                    ChangelogEntry(**entry)
                    for entry in meta_data.get("changelog", [])
                ],
            )

        return cls(
            agent_id=data["agent_id"],
            version=data["version"],
            status=AgentStatus(data["status"]),
            role=data["role"],
            capabilities=data.get("capabilities", []),
            required_inputs=data.get("required_inputs", []),
            optional_inputs=data.get("optional_inputs", []),
            outputs=data.get("outputs", []),
            output_schemas=data.get("output_schemas", {}),
            tools=data.get("tools", []),
            constraints=data.get("constraints", []),
            depends_on=data.get("depends_on", []),
            required_inputs_from=data.get("required_inputs_from", {}),
            environment=environment,
            evaluation=evaluation,
            metadata=metadata,
        )
