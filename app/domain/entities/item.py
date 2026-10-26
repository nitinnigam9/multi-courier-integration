"""Item entity."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Item:
    """A named item tracked by the API."""

    id: UUID
    name: str
    created_at: datetime
