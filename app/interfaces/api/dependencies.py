"""Request dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from app.application.use_cases.items import CreateItem, GetItem, ListItems
from app.interfaces.api.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_create_item(
    container: Annotated[Container, Depends(get_container)],
) -> CreateItem:
    return container.create_item


def get_get_item(
    container: Annotated[Container, Depends(get_container)],
) -> GetItem:
    return container.get_item


def get_list_items(
    container: Annotated[Container, Depends(get_container)],
) -> ListItems:
    return container.list_items
