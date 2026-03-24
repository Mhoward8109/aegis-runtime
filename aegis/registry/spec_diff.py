"""Spec Diff Classifier — Contract 1 §1.4.

Classifies the difference between two AgentSpec versions and determines
the minimum required SemVer bump.

Version rules:
  Major (X.0.0): Breaking change to required_inputs, outputs, output_schemas,
                  depends_on, required_inputs_from, or tools.
  Minor (x.Y.0): Additive or behavioral change to capabilities, optional_inputs,
                  evaluation, constraints, or environment.
  Patch (x.y.Z): Non-execution changes to metadata, role, or changelog.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aegis.models.agent_spec import AgentSpec
from aegis.models.enums import VersionBump


# Fields whose changes require a MAJOR bump
_MAJOR_FIELDS = {
    "required_inputs",
    "outputs",
    "output_schemas",
    "depends_on",
    "required_inputs_from",
    "tools",
}

# Fields whose changes require a MINOR bump
_MINOR_FIELDS = {
    "capabilities",
    "optional_inputs",
    "constraints",
}

# Nested objects whose changes require a MINOR bump
_MINOR_NESTED = {
    "evaluation",
    "environment",
}

# Fields whose changes require only a PATCH bump
_PATCH_FIELDS = {
    "role",
    "metadata",
}


@dataclass
class SpecDiff:
    """Result of comparing two agent spec versions."""
    required_bump: VersionBump
    changes: list[FieldChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0


@dataclass
class FieldChange:
    """A single field-level change between spec versions."""
    field_name: str
    bump_class: VersionBump
    old_value: object = None
    new_value: object = None
    description: str = ""


def classify_diff(old: AgentSpec, new: AgentSpec) -> SpecDiff:
    """Compare two specs and classify the required version bump.

    Args:
        old: The currently registered spec.
        new: The proposed updated spec.

    Returns:
        SpecDiff with required bump level and list of individual field changes.

    Raises:
        ValueError: If agent_ids don't match (can't diff different agents).
    """
    if old.agent_id != new.agent_id:
        raise ValueError(
            f"Cannot diff specs for different agents: "
            f"'{old.agent_id}' vs '{new.agent_id}'"
        )

    changes: list[FieldChange] = []

    # Check major fields
    for field_name in _MAJOR_FIELDS:
        old_val = getattr(old, field_name)
        new_val = getattr(new, field_name)
        if _values_differ(old_val, new_val):
            change_type = _classify_collection_change(old_val, new_val)
            # Additive changes to some major fields are still major
            # because downstream consumers may depend on exact shape
            changes.append(FieldChange(
                field_name=field_name,
                bump_class=VersionBump.MAJOR if change_type == "breaking" else VersionBump.MAJOR,
                old_value=old_val,
                new_value=new_val,
                description=f"{field_name} changed ({change_type})",
            ))

    # Check minor fields
    for field_name in _MINOR_FIELDS:
        old_val = getattr(old, field_name)
        new_val = getattr(new, field_name)
        if _values_differ(old_val, new_val):
            changes.append(FieldChange(
                field_name=field_name,
                bump_class=VersionBump.MINOR,
                old_value=old_val,
                new_value=new_val,
                description=f"{field_name} changed",
            ))

    # Check minor nested objects
    for field_name in _MINOR_NESTED:
        old_val = getattr(old, field_name)
        new_val = getattr(new, field_name)
        if _nested_differs(old_val, new_val):
            changes.append(FieldChange(
                field_name=field_name,
                bump_class=VersionBump.MINOR,
                old_value=str(old_val),
                new_value=str(new_val),
                description=f"{field_name} configuration changed",
            ))

    # Check patch fields
    for field_name in _PATCH_FIELDS:
        old_val = getattr(old, field_name)
        new_val = getattr(new, field_name)
        if _values_differ(old_val, new_val):
            changes.append(FieldChange(
                field_name=field_name,
                bump_class=VersionBump.PATCH,
                old_value=old_val,
                new_value=new_val,
                description=f"{field_name} changed (metadata only)",
            ))

    # Status changes are minor (affects routing behavior)
    if old.status != new.status:
        changes.append(FieldChange(
            field_name="status",
            bump_class=VersionBump.MINOR,
            old_value=old.status.value,
            new_value=new.status.value,
            description=f"status changed from {old.status.value} to {new.status.value}",
        ))

    # Determine overall required bump
    if not changes:
        required_bump = VersionBump.NONE
    else:
        bump_priority = {VersionBump.MAJOR: 3, VersionBump.MINOR: 2, VersionBump.PATCH: 1}
        required_bump = max(
            (c.bump_class for c in changes),
            key=lambda b: bump_priority.get(b, 0),
        )

    return SpecDiff(required_bump=required_bump, changes=changes)


def validate_version_bump(old: AgentSpec, new: AgentSpec) -> tuple[bool, str]:
    """Check if the version bump in `new` is sufficient for the changes made.

    Returns:
        (is_valid, reason) tuple. is_valid is True if bump is sufficient.
    """
    diff = classify_diff(old, new)

    if not diff.has_changes:
        if old.version == new.version:
            return False, (
                f"Version {new.version} is already registered with identical spec. "
                f"No re-registration at same version."
            )
        return True, "Version bumped with no detected changes (acceptable)"

    old_v = old.version_tuple
    new_v = new.version_tuple

    # Version must not decrease
    if new_v <= old_v:
        return False, (
            f"Version must increase: {old.version} → {new.version} "
            f"is not an increase"
        )

    actual_bump = _detect_bump_level(old_v, new_v)

    bump_rank = {VersionBump.PATCH: 1, VersionBump.MINOR: 2, VersionBump.MAJOR: 3}
    required_rank = bump_rank.get(diff.required_bump, 0)
    actual_rank = bump_rank.get(actual_bump, 0)

    if actual_rank < required_rank:
        change_descriptions = "; ".join(c.description for c in diff.changes)
        return False, (
            f"Insufficient version bump: changes require {diff.required_bump.value} "
            f"but only {actual_bump.value} was provided "
            f"({old.version} → {new.version}). "
            f"Changes: {change_descriptions}"
        )

    return True, f"Version bump {actual_bump.value} is sufficient for {diff.required_bump.value} changes"


def _detect_bump_level(
    old: tuple[int, int, int],
    new: tuple[int, int, int],
) -> VersionBump:
    """Determine what kind of bump occurred between two version tuples."""
    if new[0] > old[0]:
        return VersionBump.MAJOR
    if new[1] > old[1]:
        return VersionBump.MINOR
    if new[2] > old[2]:
        return VersionBump.PATCH
    return VersionBump.NONE


def _values_differ(old: object, new: object) -> bool:
    """Compare two values, handling lists and dicts correctly."""
    if isinstance(old, list) and isinstance(new, list):
        return sorted(str(x) for x in old) != sorted(str(x) for x in new)
    if isinstance(old, dict) and isinstance(new, dict):
        return old != new
    return old != new


def _nested_differs(old: object, new: object) -> bool:
    """Compare two nested config objects by their dict representation."""
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    # Compare by converting to comparable form
    old_attrs = {k: v for k, v in vars(old).items() if not k.startswith("_")}
    new_attrs = {k: v for k, v in vars(new).items() if not k.startswith("_")}
    return old_attrs != new_attrs


def _classify_collection_change(
    old: object, new: object
) -> str:
    """Classify whether a collection change is 'breaking' or 'additive'."""
    if isinstance(old, list) and isinstance(new, list):
        old_set = set(str(x) for x in old)
        new_set = set(str(x) for x in new)
        if old_set - new_set:
            return "breaking"  # items removed
        if new_set - old_set:
            return "additive"  # items only added
        return "reordered"
    if isinstance(old, dict) and isinstance(new, dict):
        if set(old.keys()) - set(new.keys()):
            return "breaking"  # keys removed
        return "additive"
    return "breaking"  # default conservative
