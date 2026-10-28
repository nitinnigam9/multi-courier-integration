"""Persistence port for booked orders."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BatchRecord:
    """Row written to the bulk_batches table."""

    batch_id: str
    total_orders: int
    status: str
    summary: str


@dataclass(frozen=True, slots=True)
class OrderRecord:
    """Row written to the orders table."""

    id: str
    order_id: str
    courier_partner: str
    status: str
    raw_request_payload: str
    raw_response_payload: str
    courier_order_id: str | None = None
    awb_number: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimResult:
    """Outcome of trying to reserve an order id before calling the courier."""

    state: str
    record: OrderRecord | None = None


class OrderRepository(Protocol):
    """Stores an order after the courier responds."""

    async def save(self, record: OrderRecord) -> None:
        """Insert the order, or update it when the same order id already exists."""

    async def get(self, order_id: str, courier_partner: str) -> OrderRecord | None:
        """Return the stored order for this courier, or None when it does not exist."""

    async def save_tracking(self, order_id: str, status: str, raw_status_payload: str) -> None:
        """Append a tracking snapshot and update the order status."""

    async def claim(self, order_id: str, courier_partner: str, raw_request_payload: str) -> ClaimResult:
        """Reserve this order id so a second submit cannot book another shipment."""

    async def create_batch(self, batch_id: str, total_orders: int, summary: str) -> None:
        """Insert a bulk batch row in PROCESSING."""

    async def update_batch(self, batch_id: str, status: str, summary: str) -> None:
        """Replace the batch status and its per-order summary."""

    async def get_batch(self, batch_id: str) -> BatchRecord | None:
        """Return the batch, or None when it does not exist."""
