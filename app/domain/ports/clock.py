"""Clock port so use cases do not call the system clock directly."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current UTC time."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC time."""
