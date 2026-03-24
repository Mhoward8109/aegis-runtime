"""Test agent spec validation — Contract 1 §1.2, §1.3.

Tests structural validation rules enforced by AgentSpec construction
and SchemaValidator.
"""

import pytest

from aegis.models.agent_spec import AgentSpec, EvaluationConfig
from aegis.models.enums import AgentStatus, EvaluatorClass
from aegis.tests.fixtures import (
    valid_agent_spec,
    valid_agent_spec_dict,
    invalid_agent_id_dict,
    invalid_agent_id_uppercase_dict,
    invalid_semver_dict,
    invalid_status_dict,
    empty_capabilities_dict,
)


class TestValidSpecPasses:
    """Well-formed specs should construct without error."""

    def test_valid_spec_constructs(self):
        spec = valid_agent_spec()
        assert spec.agent_id == "engineering.frontend-developer"
        assert spec.version == "1.0.0"
        assert spec.status == AgentStatus.ACTIVE

    def test_valid_spec_from_dict(self):
        spec = AgentSpec.from_dict(valid_agent_spec_dict())
        assert spec.agent_id == "engineering.frontend-developer"
        assert spec.status == AgentStatus.ACTIVE

    def test_valid_spec_roundtrip(self):
        original = valid_agent_spec()
        as_dict = original.to_dict()
        restored = AgentSpec.from_dict(as_dict)
        assert restored.agent_id == original.agent_id
        assert restored.version == original.version
        assert restored.capabilities == original.capabilities
        assert restored.required_inputs == original.required_inputs
        assert restored.optional_inputs == original.optional_inputs

    def test_version_tuple_parsing(self):
        spec = valid_agent_spec()
        assert spec.version_tuple == (1, 0, 0)

    def test_domain_and_name_extraction(self):
        spec = valid_agent_spec()
        assert spec.domain == "engineering"
        assert spec.name == "frontend-developer"


class TestInvalidAgentId:
    """agent_id must match pattern domain.agent-name."""

    def test_missing_dot_separator(self):
        with pytest.raises(ValueError, match="agent_id"):
            AgentSpec.from_dict(invalid_agent_id_dict())

    def test_uppercase_rejected(self):
        with pytest.raises(ValueError, match="agent_id"):
            AgentSpec.from_dict(invalid_agent_id_uppercase_dict())

    def test_empty_string_rejected(self):
        d = valid_agent_spec_dict()
        d["agent_id"] = ""
        with pytest.raises(ValueError, match="agent_id"):
            AgentSpec.from_dict(d)

    def test_special_characters_rejected(self):
        d = valid_agent_spec_dict()
        d["agent_id"] = "eng@neering.front end"
        with pytest.raises(ValueError, match="agent_id"):
            AgentSpec.from_dict(d)


class TestInvalidSemver:
    """version must be valid X.Y.Z semver."""

    def test_prefix_v_rejected(self):
        with pytest.raises(ValueError, match="version"):
            AgentSpec.from_dict(invalid_semver_dict())

    def test_two_part_rejected(self):
        d = valid_agent_spec_dict()
        d["version"] = "1.0"
        with pytest.raises(ValueError, match="version"):
            AgentSpec.from_dict(d)

    def test_non_numeric_rejected(self):
        d = valid_agent_spec_dict()
        d["version"] = "one.two.three"
        with pytest.raises(ValueError, match="version"):
            AgentSpec.from_dict(d)


class TestInvalidStatus:
    """status must be from the AgentStatus enum."""

    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError):
            AgentSpec.from_dict(invalid_status_dict())


class TestEmptyCapabilities:
    """capabilities must have at least one entry."""

    def test_empty_capabilities_rejected(self):
        with pytest.raises(ValueError, match="capabilities"):
            AgentSpec.from_dict(empty_capabilities_dict())


class TestOptionalFieldDefaults:
    """Optional fields should have correct defaults when omitted."""

    def test_optional_inputs_default_empty(self):
        d = valid_agent_spec_dict()
        d.pop("optional_inputs", None)
        spec = AgentSpec.from_dict(d)
        assert spec.optional_inputs == []

    def test_output_schemas_default_empty(self):
        d = valid_agent_spec_dict()
        d.pop("output_schemas", None)
        spec = AgentSpec.from_dict(d)
        assert spec.output_schemas == {}

    def test_depends_on_default_empty(self):
        d = valid_agent_spec_dict()
        d.pop("depends_on", None)
        spec = AgentSpec.from_dict(d)
        assert spec.depends_on == []

    def test_environment_defaults(self):
        d = valid_agent_spec_dict()
        d.pop("environment", None)
        spec = AgentSpec.from_dict(d)
        assert spec.environment.runtime == "any"
        assert spec.environment.sandbox_required is True
        assert spec.environment.max_execution_seconds == 300


class TestEvaluationConfig:
    """Evaluation block validation."""

    def test_empty_success_criteria_rejected(self):
        with pytest.raises(ValueError, match="success_criteria"):
            EvaluationConfig(success_criteria=[])

    def test_max_retries_over_5_rejected(self):
        with pytest.raises(ValueError, match="max_retries"):
            EvaluationConfig(success_criteria=["test"], max_retries=6)

    def test_negative_retries_rejected(self):
        with pytest.raises(ValueError, match="max_retries"):
            EvaluationConfig(success_criteria=["test"], max_retries=-1)


class TestOutputSchemaRelation:
    """output_schemas keys must reference declared outputs."""

    def test_unknown_output_in_schema_rejected(self):
        d = valid_agent_spec_dict()
        d["output_schemas"] = {"nonexistent_output": "schemas/test.json"}
        with pytest.raises(ValueError, match="unknown outputs"):
            AgentSpec.from_dict(d)


class TestRequiredInputsFromRelation:
    """required_inputs_from keys must reference declared inputs."""

    def test_unknown_input_source_rejected(self):
        d = valid_agent_spec_dict()
        d["required_inputs_from"] = {"nonexistent_input": "some.agent"}
        with pytest.raises(ValueError, match="unknown inputs"):
            AgentSpec.from_dict(d)

    def test_valid_input_source_accepted(self):
        d = valid_agent_spec_dict()
        d["required_inputs_from"] = {"task_spec": "product.planner"}
        spec = AgentSpec.from_dict(d)
        assert spec.required_inputs_from["task_spec"] == "product.planner"
