"""Dependency container assembled by the composition root."""

from dataclasses import dataclass

from app.application.ports.rate_limiter import RateLimiter
from app.application.use_cases.cancel_order import CancelOrder
from app.application.use_cases.create_order import CreateOrder
from app.application.use_cases.submit_bulk_orders import SubmitBulkOrders
from app.application.use_cases.track_order import TrackOrder
from app.infrastructure.config import Settings


@dataclass(slots=True)
class Container:
    """Objects the routers need. Built once in create_app."""

    settings: Settings
    rate_limiter: RateLimiter
    create_order: CreateOrder
    track_order: TrackOrder
    cancel_order: CancelOrder
    submit_bulk: SubmitBulkOrders
