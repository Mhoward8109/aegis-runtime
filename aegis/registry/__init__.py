"""Aegis agent registry — P0 runtime infrastructure."""

from aegis.registry.agent_registry import AgentRegistry, RegistrationResult
from aegis.registry.capability_vocabulary import CapabilityVocabulary, ValidationResult
from aegis.registry.schema_validator import SchemaValidator, SchemaValidationResult
from aegis.registry.spec_diff import SpecDiff, FieldChange, classify_diff, validate_version_bump
from aegis.registry.trust_registry import TrustRegistry

__all__ = [
    "AgentRegistry",
    "CapabilityVocabulary",
    "FieldChange",
    "RegistrationResult",
    "SchemaValidationResult",
    "SchemaValidator",
    "SpecDiff",
    "TrustRegistry",
    "ValidationResult",
    "classify_diff",
    "validate_version_bump",
]
