
import time
from dataclasses import dataclass


TIER_ORDER = ["low", "medium", "high"]

SATURATION_COOLDOWN_S = 30.0
FAILURE_THRESHOLD = 3


@dataclass
class TierState:
    consecutive_failures: int = 0
    saturated_until: float = 0.0  # monotonic time; 0 means not currently saturated


class LLMBalancer:
    def __init__(self):
        self.tiers = {name: TierState() for name in TIER_ORDER}

    def route(self, complexity: str) -> str:
        """Returns the tier name to use, skipping tiers currently marked saturated."""
        if complexity not in self.tiers:
            complexity = TIER_ORDER[0]

        idx = TIER_ORDER.index(complexity)
        now = time.monotonic()

        for candidate in TIER_ORDER[idx:]:
            if self.tiers[candidate].saturated_until <= now:
                return candidate

        # Every tier from the requested one upward is saturated.
        # Falling back to the lowest tier rather than raising — decide if
        # your rubric/agents would rather this raise instead, so a fully
        # saturated system fails loudly rather than degrading silently.
        return TIER_ORDER[0]

    def mark_failure(self, tier: str) -> None:
        state = self.tiers[tier]
        state.consecutive_failures += 1
        if state.consecutive_failures >= FAILURE_THRESHOLD:
            state.saturated_until = time.monotonic() + SATURATION_COOLDOWN_S

    def mark_success(self, tier: str) -> None:
        state = self.tiers[tier]
        state.consecutive_failures = 0
        state.saturated_until = 0.0

    def next_tier(self, tier: str):
        idx = TIER_ORDER.index(tier)
        if idx + 1 < len(TIER_ORDER):
            return TIER_ORDER[idx + 1]
        return None
