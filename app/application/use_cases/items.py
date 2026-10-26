"""Item use cases."""

from uuid import UUID, uuid4

from app.domain.entities.item import Item
from app.domain.exceptions import InvalidItem, ItemNotFound
from app.domain.ports.clock import Clock
from app.domain.ports.item_repository import ItemRepository

_MAX_NAME_LENGTH = 120


class CreateItem:
    """Create an item after enforcing the name invariant."""

    def __init__(self, repository: ItemRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def execute(self, name: str) -> Item:
        cleaned = name.strip()
        if not cleaned or len(cleaned) > _MAX_NAME_LENGTH:
            raise InvalidItem("name must be 1-120 characters")
        item = Item(id=uuid4(), name=cleaned, created_at=self._clock.now())
        await self._repository.add(item)
        return item


class GetItem:
    """Load one item by id."""

    def __init__(self, repository: ItemRepository) -> None:
        self._repository = repository

    async def execute(self, item_id: UUID) -> Item:
        item = await self._repository.get(item_id)
        if item is None:
            raise ItemNotFound(item_id)
        return item


class ListItems:
    """Load every item in insertion order."""

    def __init__(self, repository: ItemRepository) -> None:
        self._repository = repository

    async def execute(self) -> list[Item]:
        return await self._repository.list()
