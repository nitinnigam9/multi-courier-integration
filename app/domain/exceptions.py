"""Domain errors raised by entities and use cases."""

from typing import Any


class DomainError(Exception):
    """Base class for errors that originate in the domain."""


class UnsupportedCourier(DomainError):
    """Raised when the requested courier partner is not configured."""

    def __init__(self, partner: str) -> None:
        self.partner = partner
        super().__init__(f"Courier partner {partner!r} is not supported")


class OrderNotFound(DomainError):
    """Raised when an order id does not exist."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        super().__init__(f"Order {order_id} was not found")


class BatchNotFound(DomainError):
    """Raised when a bulk batch id does not exist."""

    def __init__(self, batch_id: str) -> None:
        self.batch_id = batch_id
        super().__init__(f"Batch {batch_id} was not found")


class OrderNotTrackable(DomainError):
    """Raised when an order has no airway bill to track."""

    def __init__(self, order_id: str) -> None:
        self.order_id = order_id
        super().__init__(f"Order {order_id} has no airway bill")


class OrderPersistenceError(DomainError):
    """Raised when an order cannot be written to the database."""

    def __init__(self, detail: str, *, manifest: Any = None) -> None:
        super().__init__(detail)
        self.manifest = manifest


class CourierRequestError(DomainError):
    """Raised when the courier partner rejects or fails a call."""

    def __init__(
        self,
        detail: str,
        *,
        operation: str = "courier",
        status_code: int = 502,
        courier_status: int | None = None,
        courier_response: Any = None,
        order_id: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.operation = operation
        self.status_code = status_code
        self.courier_status = courier_status
        self.courier_response = courier_response
        self.order_id = order_id
