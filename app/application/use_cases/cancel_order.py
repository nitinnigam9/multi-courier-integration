"""Cancel a stored order with the courier."""

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.application.ports.courier import CourierGateway
from app.domain.exceptions import CourierRequestError, OrderNotFound, OrderNotTrackable, OrderPersistenceError
from app.domain.ports.order_repository import OrderRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CancelledOrder:
    """Courier accepted the cancellation."""

    order_id: str
    awb_number: str
    courier_partner: str
    cancellation: Any


class CancelOrder:
    """Cancel an order by its stored airway bill."""

    def __init__(self, orders: OrderRepository, courier: CourierGateway) -> None:
        self._orders = orders
        self._courier = courier

    async def execute(self, order_id: str, courier_partner: str) -> CancelledOrder:
        record = await self._orders.get(order_id, courier_partner.strip())
        if record is None:
            raise OrderNotFound(order_id)
        if not record.awb_number:
            raise OrderNotTrackable(order_id)
        try:
            cancellation = await self._courier.cancel(record.awb_number)
        except CourierRequestError as exc:
            exc.order_id = exc.order_id or order_id
            raise
        try:
            await self._orders.save_tracking(order_id, "CANCELLED", _json(cancellation))
        except OrderPersistenceError:
            logger.exception("cancellation was accepted but not stored for order_id=%s", order_id)
        return CancelledOrder(
            order_id=record.order_id,
            awb_number=record.awb_number,
            courier_partner=record.courier_partner,
            cancellation=cancellation,
        )


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
