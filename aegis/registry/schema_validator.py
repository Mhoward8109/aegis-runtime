"""Schema Validator — Contract 1 §1.3.

Validates agent specs at registration time. This is the enforcement
boundary that prevents malformed specs from entering the system.

Validation layers:
1. Structural: required fields, types, patterns
2. Semantic: capability vocabulary, output schema resolvability
3. Relational: version enforcement against existing specs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from aegis.models.agent_spec import AgentSpec
from aegis.registry.capability_vocabulary import CapabilityVocabulary


@dataclass
class SchemaValidationResult:
    """Result of full schema validation."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SchemaValidator:
    """Validates agent specs against Contract 1 requirements.

    Performs structural, semantic, and relational validation.
    Used by AgentRegistry at registration time.
    """

    def __init__(
        self,
        vocabulary: CapabilityVocabulary,
        schema_base_path: str | Path | None = None,
    ) -> None:
        """Initialize validator.

        Args:
            vocabulary: Capability vocabulary for tag validation.
            schema_base_path: Base directory for resolving output_schemas references.
                If None, output schema resolution is skipped (useful for testing).
        """
        self._vocabulary = vocabulary
        self._schema_base_path = Path(schema_base_path) if schema_base_path else None

    def validate(self, spec: AgentSpec) -> SchemaValidationResult:
        """Run full validation on an agent spec.

        This is called by the registry before registration. It checks:
        1. Structural validity (handled by AgentSpec.__post_init__)
        2. Capability vocabulary conformance
        3. Output schema resolvability
        4. Tool registration (stub — deferred to governor integration)

        Returns:
            SchemaValidationResult with errors and warnings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Structural validation is already done by AgentSpec construction.
        #    If we got an AgentSpec instance, it passed structural checks.

        # 2. Capability vocabulary
        cap_result = self._vocabulary.validate(spec.capabilities)
        if not cap_result.valid:
            errors.append(
                f"Unknown capabilities: {cap_result.unknown_capabilities}. "
                f"Register new capabilities before use."
            )

        # 3. Output schema resolvability (Contract 1 §1.3 + A1.1 fix)
        if self._schema_base_path and spec.output_schemas:
            for output_name, schema_ref in spec.output_schemas.items():
                schema_path = self._schema_base_path / schema_ref
                if not schema_path.exists():
                    errors.append(
                        f"Output schema for '{output_name}' references "
                        f"'{schema_ref}' which does not exist at "
                        f"'{schema_path}'"
                    )

        # 4. Warn on missing output schemas for outputs
        outputs_without_schemas = set(spec.outputs) - set(spec.output_schemas.keys())
        if outputs_without_schemas:
            warnings.append(
                f"Outputs without schema references: {outputs_without_schemas}. "
                f"Consider adding output_schemas for evaluator validation."
            )

        # 5. Dependency self-reference check
        if spec.agent_id in spec.depends_on:
            errors.append(
                f"Agent cannot depend on itself: '{spec.agent_id}' in depends_on"
            )

        # 6. Required inputs from references should point to valid agent IDs
        #    (full validation requires registry — this just checks format)
        for input_name, source_id in spec.required_inputs_from.items():
            from aegis.models.agent_spec import AGENT_ID_PATTERN
            if not AGENT_ID_PATTERN.match(source_id):
                errors.append(
                    f"required_inputs_from['{input_name}'] references "
                    f"'{source_id}' which is not a valid agent_id pattern"
                )

        return SchemaValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
