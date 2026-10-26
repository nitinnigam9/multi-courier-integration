"""Sliding-window rate limiter.

A request is allowed only when every policy still has quota. Rejected
requests are not recorded, so retries do not consume extra quota. The
check and the record happen under one lock; a Redis adapter would do
the same work in one script so the decision stays atomic.
"""

import asyncio
import math
import time
from collections import defaultdict, deque
from collections.abc import Callable

from app.application.ports.rate_limiter import (
    PolicyStatus,
    QuotaPolicy,
    RateLimitDecision,
)


class SlidingWindowRateLimiter:
    """Counts requests in a rolling window for each (partition, policy) pair."""

    def __init__(
        self,
        policies: tuple[QuotaPolicy, ...] | list[QuotaPolicy],
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not policies:
            raise ValueError("at least one quota policy is required")
        names = [policy.name for policy in policies]
        if len(names) != len(set(names)):
            raise ValueError("quota policy names must be unique")
        self._policies = tuple(policies)
        self._clock = clock or time.monotonic
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    @property
    def policies(self) -> tuple[QuotaPolicy, ...]:
        return self._policies

    async def consume(self, partition: str) -> RateLimitDecision:
        now = self._clock()
        async with self._lock:
            windows = [self._prune(partition, policy, now) for policy in self._policies]
            allowed = all(
                len(window) < policy.quota
                for window, policy in zip(windows, self._policies, strict=True)
            )
            if allowed:
                for window in windows:
                    window.append(now)
            statuses = tuple(
                _status(policy, window, now=now, committed=allowed)
                for policy, window in zip(self._policies, windows, strict=True)
            )
            return RateLimitDecision(allowed=allowed, policies=statuses)

    def _prune(self, partition: str, policy: QuotaPolicy, now: float) -> deque[float]:
        window = self._hits[(partition, policy.name)]
        cutoff = now - policy.window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        return window


def _status(
    policy: QuotaPolicy,
    window: deque[float],
    *,
    now: float,
    committed: bool,
) -> PolicyStatus:
    used = len(window)
    policy_allowed = used <= policy.quota if committed else used < policy.quota
    remaining = max(0, policy.quota - used) if policy_allowed else 0
    if window:
        reset_seconds = max(0, math.ceil(window[0] + policy.window_seconds - now - 1e-9))
    else:
        reset_seconds = policy.window_seconds
    return PolicyStatus(
        name=policy.name,
        quota=policy.quota,
        window_seconds=policy.window_seconds,
        remaining=remaining,
        reset_seconds=reset_seconds,
        allowed=policy_allowed,
    )
