"""Request and response schemas for items."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.entities.item import Item


class ItemCreate(BaseModel):
    """Body for creating an item."""

    name: str = Field(min_length=1, max_length=120)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class ItemResponse(BaseModel):
    """Public representation of an item."""

    id: UUID
    name: str
    created_at: datetime

    @classmethod
    def from_entity(cls, item: Item) -> "ItemResponse":
        return cls(id=item.id, name=item.name, created_at=item.created_at)
