"""Test version enforcement — Contract 1 §1.4.

Tests the spec diff classifier and version bump validation rules:
  Major: breaking required_inputs, outputs, output_schemas, depends_on,
         required_inputs_from, tools
  Minor: additive capabilities, optional_inputs, evaluation, constraints,
         environment, status
  Patch: metadata, role, changelog
"""

import pytest

from aegis.models.agent_spec import AgentSpec, EvaluationConfig
from aegis.models.enums import AgentStatus, VersionBump
from aegis.registry.spec_diff import classify_diff, validate_version_bump
from aegis.tests.fixtures import valid_agent_spec


def _make_updated(base: AgentSpec, **overrides) -> AgentSpec:
    """Create a modified copy of an AgentSpec with overrides.

    Bypasses __post_init__ validation by constructing via from_dict.
    """
    d = base.to_dict()
    for key, value in overrides.items():
        if key == "version":
            d["version"] = value
        elif key == "status":
            d["status"] = value if isinstance(value, str) else value.value
        elif key == "evaluation":
            d["evaluation"] = value
        else:
            d[key] = value
    return AgentSpec.from_dict(d)


class TestBreakingChangeRequiresMajor:
    """Changes to major fields require major version bump."""

    def test_removing_required_input(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="2.0.0", required_inputs=["task_spec"])
        # Removed "design_spec" from required_inputs

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.MAJOR

    def test_changing_outputs(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="2.0.0", outputs=["different_output"])

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.MAJOR

    def test_changing_tools(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="2.0.0", tools=["code_editor"])
        # Removed browser_test and linter

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.MAJOR

    def test_changing_depends_on(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="2.0.0", depends_on=["other.agent"])

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.MAJOR

    def test_major_bump_with_minor_version_rejected(self):
        old = valid_agent_spec()
        # Breaking change (removed required input) with only minor bump
        new = _make_updated(old, version="1.1.0", required_inputs=["task_spec"])

        valid, reason = validate_version_bump(old, new)
        assert valid is False
        assert "major" in reason.lower()

    def test_major_bump_with_major_version_accepted(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="2.0.0", required_inputs=["task_spec"])

        valid, reason = validate_version_bump(old, new)
        assert valid is True


class TestAdditiveChangeIsMinor:
    """Additive changes to minor fields require at least minor bump."""

    def test_adding_capability(self):
        old = valid_agent_spec()
        new_caps = list(old.capabilities) + ["write_tests"]
        new = _make_updated(old, version="1.1.0", capabilities=new_caps)

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.MINOR

    def test_adding_optional_input(self):
        old = valid_agent_spec()
        new_opts = list(old.optional_inputs) + ["extra_context"]
        new = _make_updated(old, version="1.1.0", optional_inputs=new_opts)

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.MINOR

    def test_adding_constraint(self):
        old = valid_agent_spec()
        new_constraints = list(old.constraints) + ["new_constraint"]
        new = _make_updated(old, version="1.1.0", constraints=new_constraints)

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.MINOR

    def test_status_change_is_minor(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="1.1.0", status="deprecated")

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.MINOR

    def test_minor_change_with_patch_bump_rejected(self):
        old = valid_agent_spec()
        new_caps = list(old.capabilities) + ["write_tests"]
        new = _make_updated(old, version="1.0.1", capabilities=new_caps)

        valid, reason = validate_version_bump(old, new)
        assert valid is False
        assert "minor" in reason.lower()

    def test_minor_change_with_minor_bump_accepted(self):
        old = valid_agent_spec()
        new_caps = list(old.capabilities) + ["write_tests"]
        new = _make_updated(old, version="1.1.0", capabilities=new_caps)

        valid, reason = validate_version_bump(old, new)
        assert valid is True


class TestMetadataChangeIsPatch:
    """Non-execution changes require only patch bump."""

    def test_role_change(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="1.0.1", role="Senior Frontend Developer")

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.PATCH

    def test_patch_change_with_patch_bump_accepted(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="1.0.1", role="Senior Frontend Developer")

        valid, reason = validate_version_bump(old, new)
        assert valid is True


class TestNoVersionDowngrade:
    """Registering lower version than current must be rejected."""

    def test_downgrade_rejected(self):
        old = valid_agent_spec()  # 1.0.0
        new = _make_updated(old, version="0.9.0", role="Downgraded")

        valid, reason = validate_version_bump(old, new)
        assert valid is False
        assert "increase" in reason.lower() or "not an increase" in reason.lower()

    def test_same_version_rejected(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="1.0.0", role="Same version different role")

        valid, reason = validate_version_bump(old, new)
        assert valid is False


class TestNoChanges:
    """No-change detection."""

    def test_identical_specs_no_changes(self):
        old = valid_agent_spec()
        new = valid_agent_spec()
        # Same agent_id, same everything

        diff = classify_diff(old, new)
        assert diff.required_bump == VersionBump.NONE
        assert not diff.has_changes


class TestDiffDifferentAgents:
    """Cannot diff specs with different agent_ids."""

    def test_different_ids_raises(self):
        old = valid_agent_spec()  # engineering.frontend-developer
        from aegis.tests.fixtures import valid_backend_agent_spec
        new = valid_backend_agent_spec()  # engineering.backend-architect

        with pytest.raises(ValueError, match="different agents"):
            classify_diff(old, new)


class TestOversizedBumpAccepted:
    """A major bump is always sufficient, even for patch-level changes."""

    def test_major_bump_for_patch_change(self):
        old = valid_agent_spec()
        new = _make_updated(old, version="2.0.0", role="Overly bumped")

        valid, reason = validate_version_bump(old, new)
        assert valid is True
