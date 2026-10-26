"""Persistence port for items."""

from typing import Protocol
from uuid import UUID

from app.domain.entities.item import Item


class ItemRepository(Protocol):
    """Storage for items. Implementations live in infrastructure."""

    async def add(self, item: Item) -> None:
        """Persist a new item."""

    async def get(self, item_id: UUID) -> Item | None:
        """Return the item, or None when it does not exist."""

    async def list(self) -> list[Item]:
        """Return items in insertion order."""
