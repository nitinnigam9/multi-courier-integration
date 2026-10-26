"""Rate limiter port.

The HTTP header mapping lives in the interface layer. This port only
describes the quota decision the limiter returns.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class QuotaPolicy:
    """A named quota allocated over a window, in requests."""

    name: str
    quota: int
    window_seconds: int

    def __post_init__(self) -> None:
        if not self.name.isascii() or not self.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"policy name {self.name!r} must be an ASCII token")
        if self.quota < 0:
            raise ValueError("quota must be zero or greater")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")


@dataclass(frozen=True, slots=True)
class PolicyStatus:
    """Current remaining quota for one policy after a request is judged."""

    name: str
    quota: int
    window_seconds: int
    remaining: int
    reset_seconds: int
    allowed: bool


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """Combined result of every policy applied to one request."""

    allowed: bool
    policies: tuple[PolicyStatus, ...]

    @property
    def violated(self) -> tuple[str, ...]:
        return tuple(policy.name for policy in self.policies if not policy.allowed)

    @property
    def retry_after_seconds(self) -> int:
        denied = [policy.reset_seconds for policy in self.policies if not policy.allowed]
        if not denied:
            return 0
        return max(denied)


class RateLimiter(Protocol):
    """Consumes one request against the active quota policies."""

    @property
    def policies(self) -> tuple[QuotaPolicy, ...]:
        """Policies enforced by this limiter, in evaluation order."""

    async def consume(self, partition: str) -> RateLimitDecision:
        """Count the request for this partition, or reject it without counting."""
