"""Create an order by booking it with the configured courier and storing the result."""

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.application.ports.courier import CourierGateway
from app.domain.entities.order import Order
from app.domain.exceptions import CourierRequestError, OrderPersistenceError, UnsupportedCourier
from app.domain.ports.order_repository import OrderRecord, OrderRepository

logger = logging.getLogger(__name__)

_AWB_KEYS = {
    "awb",
    "awbnumber",
    "awb_number",
    "awbno",
    "waybill",
    "waybillno",
    "trackingnumber",
    "tracking_number",
    "lrnumber",
}
_COURIER_ORDER_KEYS = {
    "courierorderid",
    "courier_order_id",
    "shipmentid",
    "shipment_id",
}


@dataclass(frozen=True, slots=True)
class CreatedOrder:
    """Order accepted by the courier partner."""

    order_id: str
    courier_partner: str
    manifest: Any


class CreateOrder:
    """Book an order with the courier configured for this service."""

    def __init__(self, courier: CourierGateway, partner_name: str, orders: OrderRepository) -> None:
        self._courier = courier
        self._partner_name = partner_name.strip()
        self._orders = orders

    async def execute(self, order: Order, request_payload: dict[str, Any]) -> CreatedOrder:
        if self._partner_name and order.courier_partner.strip().lower() != self._partner_name.lower():
            raise UnsupportedCourier(order.courier_partner)
        try:
            manifest = await self._courier.create_shipment(order)
        except CourierRequestError as exc:
            await self._save(order, request_payload, "FAILED", exc.courier_response or {"detail": str(exc)})
            raise
        await self._save(order, request_payload, "MANIFESTED", manifest, required=True)
        return CreatedOrder(
            order_id=order.order_id,
            courier_partner=order.courier_partner,
            manifest=manifest,
        )

    async def _save(
        self,
        order: Order,
        request_payload: dict[str, Any],
        status: str,
        response_payload: Any,
        *,
        required: bool = False,
    ) -> None:
        awb_number, courier_order_id = _identifiers(response_payload, order.order_id)
        record = OrderRecord(
            id=str(uuid4()),
            order_id=order.order_id,
            courier_partner=order.courier_partner,
            status=status,
            raw_request_payload=_json(request_payload),
            raw_response_payload=_json(response_payload),
            courier_order_id=courier_order_id,
            awb_number=awb_number,
        )
        try:
            await self._orders.save(record)
        except OrderPersistenceError:
            if required:
                raise OrderPersistenceError(
                    f"Order {order.order_id} was booked but could not be saved",
                    manifest=response_payload,
                ) from None
            logger.exception("failed to store courier failure for order_id=%s", order.order_id)


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _identifiers(payload: Any, order_id: str) -> tuple[str | None, str | None]:
    awb = _find(payload, _AWB_KEYS)
    courier_order_id = _find(payload, _COURIER_ORDER_KEYS)
    if courier_order_id == order_id:
        courier_order_id = None
    return awb, courier_order_id


def _find(payload: Any, keys: set[str]) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in keys and value not in (None, ""):
                return str(value)
        for value in payload.values():
            found = _find(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find(item, keys)
            if found:
                return found
    return None
