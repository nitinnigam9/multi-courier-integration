"""Dependency container assembled by the composition root."""

from dataclasses import dataclass

from app.application.ports.rate_limiter import RateLimiter
from app.application.use_cases.items import CreateItem, GetItem, ListItems
from app.domain.ports.item_repository import ItemRepository
from app.infrastructure.config import Settings


@dataclass(slots=True)
class Container:
    """Objects the routers need. Built once in create_app."""

    settings: Settings
    repository: ItemRepository
    rate_limiter: RateLimiter
    create_item: CreateItem
    get_item: GetItem
    list_items: ListItems
