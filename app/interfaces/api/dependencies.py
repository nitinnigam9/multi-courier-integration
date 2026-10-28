"""Request dependencies."""

from typing import Annotated

from fastapi import Depends, Request

from app.application.use_cases.cancel_order import CancelOrder
from app.application.use_cases.create_order import CreateOrder
from app.application.use_cases.submit_bulk_orders import SubmitBulkOrders
from app.application.use_cases.track_order import TrackOrder
from app.interfaces.api.container import Container


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_create_order(
    container: Annotated[Container, Depends(get_container)],
) -> CreateOrder:
    return container.create_order


def get_track_order(
    container: Annotated[Container, Depends(get_container)],
) -> TrackOrder:
    return container.track_order


def get_cancel_order(
    container: Annotated[Container, Depends(get_container)],
) -> CancelOrder:
    return container.cancel_order


def get_submit_bulk(
    container: Annotated[Container, Depends(get_container)],
) -> SubmitBulkOrders:
    return container.submit_bulk
