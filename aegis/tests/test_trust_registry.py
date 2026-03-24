"""Test trust registry — Contract 5 §5.3.

Tests governance-owned trust tier management.
"""

import pytest

from aegis.models.enums import TrustTier
from aegis.registry.trust_registry import TrustRegistry


@pytest.fixture
def trust() -> TrustRegistry:
    return TrustRegistry()


class TestUnknownAgentDefaultsToLow:
    """Agents not in trust registry return TrustTier.LOW."""

    def test_unknown_agent(self, trust: TrustRegistry):
        tier = trust.get_trust("unknown.agent")
        assert tier == TrustTier.LOW

    def test_get_entry_returns_none(self, trust: TrustRegistry):
        entry = trust.get_entry("unknown.agent")
        assert entry is None


class TestSetAndGetTrust:
    """Basic set → get roundtrip."""

    def test_set_medium(self, trust: TrustRegistry):
        entry = trust.set_trust(
            agent_id="engineering.frontend-developer",
            tier=TrustTier.MEDIUM,
            granted_by="operator-mike",
            notes="Promoted after 50 successful tasks",
        )
        assert entry.trust_tier == TrustTier.MEDIUM
        assert entry.granted_by == "operator-mike"

        # Get should return the tier
        assert trust.get_trust("engineering.frontend-developer") == TrustTier.MEDIUM

    def test_set_high(self, trust: TrustRegistry):
        trust.set_trust("testing.api-tester", TrustTier.HIGH, "operator-mike")
        assert trust.get_trust("testing.api-tester") == TrustTier.HIGH

    def test_set_critical(self, trust: TrustRegistry):
        trust.set_trust("system.orchestrator", TrustTier.CRITICAL, "operator-mike")
        assert trust.get_trust("system.orchestrator") == TrustTier.CRITICAL

    def test_get_entry_has_metadata(self, trust: TrustRegistry):
        trust.set_trust(
            agent_id="engineering.frontend-developer",
            tier=TrustTier.MEDIUM,
            granted_by="operator-mike",
            notes="Good track record",
            review_due="2026-06-19",
        )
        entry = trust.get_entry("engineering.frontend-developer")
        assert entry is not None
        assert entry.granted_by == "operator-mike"
        assert entry.review_due == "2026-06-19"
        assert entry.notes == "Good track record"
        assert entry.granted_at != ""  # Should be auto-populated


class TestTrustUpdate:
    """Updating trust preserves history."""

    def test_update_preserves_history(self, trust: TrustRegistry):
        trust.set_trust("eng.dev", TrustTier.LOW, "operator-a", notes="Initial")
        trust.set_trust("eng.dev", TrustTier.MEDIUM, "operator-a", notes="Promoted")
        trust.set_trust("eng.dev", TrustTier.HIGH, "operator-b", notes="Further promoted")

        history = trust.get_history("eng.dev")
        assert len(history) == 3
        assert history[0].trust_tier == TrustTier.LOW
        assert history[1].trust_tier == TrustTier.MEDIUM
        assert history[2].trust_tier == TrustTier.HIGH

    def test_current_tier_is_latest(self, trust: TrustRegistry):
        trust.set_trust("eng.dev", TrustTier.LOW, "op")
        trust.set_trust("eng.dev", TrustTier.HIGH, "op")
        assert trust.get_trust("eng.dev") == TrustTier.HIGH


class TestTrustRemoval:
    """Removing trust reverts agent to default LOW."""

    def test_remove_reverts_to_low(self, trust: TrustRegistry):
        trust.set_trust("eng.dev", TrustTier.HIGH, "op")
        assert trust.get_trust("eng.dev") == TrustTier.HIGH

        removed = trust.remove("eng.dev")
        assert removed is True
        assert trust.get_trust("eng.dev") == TrustTier.LOW

    def test_remove_nonexistent_returns_false(self, trust: TrustRegistry):
        assert trust.remove("nonexistent.agent") is False

    def test_remove_preserves_history(self, trust: TrustRegistry):
        trust.set_trust("eng.dev", TrustTier.MEDIUM, "op")
        trust.remove("eng.dev")

        history = trust.get_history("eng.dev")
        assert len(history) == 1  # Archived entry
        assert history[0].trust_tier == TrustTier.MEDIUM


class TestListAndContains:
    """Registry listing and membership checks."""

    def test_list_entries(self, trust: TrustRegistry):
        trust.set_trust("a.one", TrustTier.LOW, "op")
        trust.set_trust("b.two", TrustTier.HIGH, "op")

        entries = trust.list_entries()
        assert len(entries) == 2
        ids = {e.agent_id for e in entries}
        assert "a.one" in ids
        assert "b.two" in ids

    def test_contains(self, trust: TrustRegistry):
        assert "eng.dev" not in trust
        trust.set_trust("eng.dev", TrustTier.MEDIUM, "op")
        assert "eng.dev" in trust

    def test_len(self, trust: TrustRegistry):
        assert len(trust) == 0
        trust.set_trust("a.one", TrustTier.LOW, "op")
        assert len(trust) == 1
