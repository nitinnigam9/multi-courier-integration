"""Load tracking for a stored order from the courier."""

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.application.ports.courier import CourierGateway
from app.domain.exceptions import CourierRequestError, OrderNotFound, OrderNotTrackable, OrderPersistenceError
from app.domain.ports.order_repository import OrderRepository

logger = logging.getLogger(__name__)

_GENERIC_STATUSES = {"success", "successful", "ok", "true", "none", "null"}
_STATUS_KEYS = (
    "currentStatusCodeDescription",
    "currentStatus",
    "current_status",
    "shipmentStatus",
    "shipment_status",
    "status",
)


@dataclass(frozen=True, slots=True)
class TrackedOrder:
    """Tracking returned by the courier for one stored order."""

    order_id: str
    awb_number: str
    courier_partner: str
    tracking: Any


class TrackOrder:
    """Read an order's airway bill and fetch its courier tracking."""

    def __init__(self, orders: OrderRepository, courier: CourierGateway) -> None:
        self._orders = orders
        self._courier = courier

    async def execute(self, order_id: str, courier_partner: str) -> TrackedOrder:
        partner = courier_partner.strip()
        record = await self._orders.get(order_id, partner)
        if record is None:
            raise OrderNotFound(order_id)
        if not record.awb_number:
            raise OrderNotTrackable(order_id)
        try:
            tracking = await self._courier.track(record.awb_number)
        except CourierRequestError as exc:
            exc.order_id = exc.order_id or order_id
            raise
        try:
            await self._orders.save_tracking(order_id, tracking_status(tracking), _json(tracking))
        except OrderPersistenceError:
            logger.exception("tracking was fetched but not stored for order_id=%s", order_id)
        return TrackedOrder(
            order_id=record.order_id,
            awb_number=record.awb_number,
            courier_partner=record.courier_partner,
            tracking=tracking,
        )


def tracking_status(payload: Any) -> str:
    """Pick a short status for the orders and tracking_history tables."""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            found = _status_value(data)
            if found:
                return found
        found = _status_value(payload)
        if found:
            return found
    return "TRACKED"


def _status_value(payload: dict[str, Any]) -> str | None:
    for key in _STATUS_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and value.strip().lower() not in _GENERIC_STATUSES:
            return value.strip()[:50]
    return None


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
