"""Item routes. They call use cases and do not touch storage directly."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.application.use_cases.items import CreateItem, GetItem, ListItems
from app.interfaces.api.dependencies import get_create_item, get_get_item, get_list_items
from app.interfaces.api.schemas.item import ItemCreate, ItemResponse

router = APIRouter(prefix="/api/v1/items", tags=["items"])


@router.post("", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: ItemCreate,
    use_case: Annotated[CreateItem, Depends(get_create_item)],
) -> ItemResponse:
    item = await use_case.execute(payload.name)
    return ItemResponse.from_entity(item)


@router.get("", response_model=list[ItemResponse])
async def list_items(
    use_case: Annotated[ListItems, Depends(get_list_items)],
) -> list[ItemResponse]:
    items = await use_case.execute()
    return [ItemResponse.from_entity(item) for item in items]


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: UUID,
    use_case: Annotated[GetItem, Depends(get_get_item)],
) -> ItemResponse:
    item = await use_case.execute(item_id)
    return ItemResponse.from_entity(item)
