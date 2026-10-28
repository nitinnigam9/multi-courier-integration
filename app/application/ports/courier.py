"""Outbound port for booking a shipment with a courier."""

from typing import Any, Protocol

from app.domain.entities.order import Order


class CourierGateway(Protocol):
    """Books a shipment and reads its tracking from the courier."""

    async def create_shipment(self, order: Order) -> Any:
        """Create the shipment. The return value is the partner response JSON."""

    async def track(self, awb: str) -> Any:
        """Return the partner's tracking payload for this airway bill."""

    async def cancel(self, awb: str) -> Any:
        """Cancel the shipment and return the partner response."""

    async def submit_manifest(self, shipment: dict[str, Any]) -> Any:
        """POST one manifest object and return the partner response JSON."""
