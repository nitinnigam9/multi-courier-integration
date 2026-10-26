"""In-process item repository."""

import asyncio
from uuid import UUID

from app.domain.entities.item import Item


class MemoryItemRepository:
    """Item storage for a single process. Swap this for a database adapter later."""

    def __init__(self) -> None:
        self._items: dict[UUID, Item] = {}
        self._order: list[UUID] = []
        self._lock = asyncio.Lock()

    async def add(self, item: Item) -> None:
        async with self._lock:
            self._items[item.id] = item
            self._order.append(item.id)

    async def get(self, item_id: UUID) -> Item | None:
        async with self._lock:
            return self._items.get(item_id)

    async def list(self) -> list[Item]:
        async with self._lock:
            return [self._items[item_id] for item_id in self._order]
