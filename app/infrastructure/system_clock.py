"""System clock adapter."""

from datetime import UTC, datetime


class SystemClock:
    """Clock backed by the host clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)
