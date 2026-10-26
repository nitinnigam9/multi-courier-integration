"""Domain errors raised by entities and use cases."""

from uuid import UUID


class DomainError(Exception):
    """Base class for errors that originate in the domain."""


class InvalidItem(DomainError):
    """Raised when an item breaks an invariant."""


class ItemNotFound(DomainError):
    """Raised when an item id does not exist."""

    def __init__(self, item_id: UUID) -> None:
        self.item_id = item_id
        super().__init__(f"Item {item_id} was not found")
