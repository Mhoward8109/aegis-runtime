"""Trust Registry — Contract 5 §5.3.

Trust is owned by governance, NOT by the agent spec. This registry is the
single source of truth for agent trust tiers, consumed by admission control.

Key behaviors:
- Unknown agents default to TrustTier.LOW
- Operators manage trust manually
- The completion reconciler can recommend changes but never applies them
- Trust changes take effect at next admission, not mid-execution (A2.2)
"""

from __future__ import annotations

from datetime import datetime, timezone

from aegis.models.enums import TrustTier
from aegis.models.trust_entry import TrustEntry


class TrustRegistry:
    """Governance-owned trust tier registry.

    Stores trust classifications for agents. Consumed by admission control
    to determine governance stringency.

    Thread safety: Not thread-safe. Wrap in a lock if used concurrently.
    """

    def __init__(self) -> None:
        # Primary storage: agent_id → current TrustEntry
        self._entries: dict[str, TrustEntry] = {}

        # History: agent_id → list of all entries (ordered by time)
        self._history: dict[str, list[TrustEntry]] = {}

    def get_trust(self, agent_id: str) -> TrustTier:
        """Return trust tier for agent.

        Default: TrustTier.LOW for unknown agents.
        This is the primary lookup used by admission control.
        """
        entry = self._entries.get(agent_id)
        if entry is None:
            return TrustTier.LOW
        return entry.trust_tier

    def set_trust(
        self,
        agent_id: str,
        tier: TrustTier,
        granted_by: str,
        notes: str = "",
        review_due: str = "",
    ) -> TrustEntry:
        """Set or update trust tier. Operator-only action.

        Args:
            agent_id: The agent to set trust for.
            tier: The new trust tier.
            granted_by: Identifier of the operator making the change.
            notes: Optional justification.
            review_due: Optional date for trust review.

        Returns:
            The created TrustEntry.
        """
        entry = TrustEntry(
            agent_id=agent_id,
            trust_tier=tier,
            granted_by=granted_by,
            granted_at=datetime.now(timezone.utc).isoformat(),
            review_due=review_due,
            notes=notes,
        )

        # Archive previous entry
        if agent_id in self._entries:
            if agent_id not in self._history:
                self._history[agent_id] = []
            self._history[agent_id].append(self._entries[agent_id])

        self._entries[agent_id] = entry
        return entry

    def get_entry(self, agent_id: str) -> TrustEntry | None:
        """Return full trust entry with metadata.

        Returns None if agent has no trust entry (defaults to LOW via get_trust).
        """
        return self._entries.get(agent_id)

    def get_history(self, agent_id: str) -> list[TrustEntry]:
        """Return trust change history for an agent."""
        history = list(self._history.get(agent_id, []))
        # Include current entry at the end
        current = self._entries.get(agent_id)
        if current:
            history.append(current)
        return history

    def list_entries(self) -> list[TrustEntry]:
        """Return all current trust entries."""
        return list(self._entries.values())

    def remove(self, agent_id: str) -> bool:
        """Remove trust entry. Agent reverts to default LOW.

        Returns True if entry existed and was removed.
        """
        entry = self._entries.pop(agent_id, None)
        if entry is None:
            return False
        # Archive the removed entry
        if agent_id not in self._history:
            self._history[agent_id] = []
        self._history[agent_id].append(entry)
        return True

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._entries
