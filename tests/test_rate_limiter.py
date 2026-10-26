"""Sliding-window limiter tests."""

import asyncio

import pytest

from app.application.ports.rate_limiter import QuotaPolicy
from app.infrastructure.rate_limit.sliding_window import SlidingWindowRateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _limiter(*policies: QuotaPolicy, clock: Clock | None = None) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(policies, clock=clock)


def test_allows_until_quota_then_rejects_without_consuming() -> None:
    clock = Clock()
    limiter = _limiter(QuotaPolicy("burst", 2, 10), clock=clock)

    first = asyncio.run(limiter.consume("a"))
    second = asyncio.run(limiter.consume("a"))
    third = asyncio.run(limiter.consume("a"))
    fourth = asyncio.run(limiter.consume("a"))

    assert first.allowed and first.policies[0].remaining == 1
    assert first.policies[0].reset_seconds == 10
    assert second.allowed and second.policies[0].remaining == 0
    assert not third.allowed
    assert third.policies[0].remaining == 0
    assert third.retry_after_seconds == 10
    assert third.violated == ("burst",)
    assert not fourth.allowed

    clock.advance(10)
    restored = asyncio.run(limiter.consume("a"))
    assert restored.allowed
    assert restored.policies[0].remaining == 1


def test_each_partition_has_its_own_window() -> None:
    limiter = _limiter(QuotaPolicy("burst", 1, 60))
    assert asyncio.run(limiter.consume("one")).allowed
    assert not asyncio.run(limiter.consume("one")).allowed
    assert asyncio.run(limiter.consume("two")).allowed


def test_both_policies_must_pass() -> None:
    clock = Clock()
    limiter = _limiter(
        QuotaPolicy("burst", 2, 10),
        QuotaPolicy("sustained", 3, 100),
        clock=clock,
    )

    assert asyncio.run(limiter.consume("a")).allowed
    assert asyncio.run(limiter.consume("a")).allowed
    blocked = asyncio.run(limiter.consume("a"))
    assert not blocked.allowed
    assert blocked.violated == ("burst",)
    assert blocked.policies[1].allowed
    assert blocked.policies[1].remaining == 1

    clock.advance(10)
    assert asyncio.run(limiter.consume("a")).allowed
    sustained = asyncio.run(limiter.consume("a"))
    assert not sustained.allowed
    assert sustained.violated == ("sustained",)
    assert sustained.policies[0].allowed
    assert sustained.retry_after_seconds == 90


def test_concurrent_requests_do_not_exceed_quota() -> None:
    limiter = _limiter(QuotaPolicy("burst", 5, 60))

    async def burst() -> int:
        decisions = await asyncio.gather(*(limiter.consume("same") for _ in range(20)))
        return sum(decision.allowed for decision in decisions)

    assert asyncio.run(burst()) == 5


def test_policy_names_must_be_unique() -> None:
    with pytest.raises(ValueError):
        _limiter(QuotaPolicy("burst", 1, 1), QuotaPolicy("burst", 2, 2))
