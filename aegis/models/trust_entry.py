"""TrustEntry model — Contract 5 §5.3.

Trust is owned by governance, NOT by the agent spec, because trust is
an operational assessment that changes independently of the agent's
self-declared properties.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aegis.models.enums import TrustTier


@dataclass
class TrustEntry:
    """Trust classification for a single agent.

    Stored in the trust registry, managed by operators.
    The completion reconciler can recommend changes but never applies them.
    """

    agent_id: str
    trust_tier: TrustTier
    granted_by: str
    granted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    review_due: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "trust_tier": self.trust_tier.value,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at,
            "review_due": self.review_due,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustEntry:
        return cls(
            agent_id=data["agent_id"],
            trust_tier=TrustTier(data["trust_tier"]),
            granted_by=data["granted_by"],
            granted_at=data.get("granted_at", ""),
            review_due=data.get("review_due", ""),
            notes=data.get("notes", ""),
        )
