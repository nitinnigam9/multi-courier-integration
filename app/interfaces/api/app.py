"""Composition root for the HTTP application."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.application.ports.courier import CourierGateway
from app.application.ports.rate_limiter import QuotaPolicy, RateLimiter
from app.application.use_cases.cancel_order import CancelOrder
from app.application.use_cases.create_order import CreateOrder
from app.application.use_cases.submit_bulk_orders import SubmitBulkOrders
from app.application.use_cases.track_order import TrackOrder
from app.domain.exceptions import (
    BatchNotFound,
    CourierRequestError,
    OrderNotFound,
    OrderNotTrackable,
    OrderPersistenceError,
    UnsupportedCourier,
)
from app.infrastructure.config import CourierSettings, Settings
from app.infrastructure.couriers.urbanebolt import UrbaneboltCourier
from app.infrastructure.persistence.mysql_order_repository import MysqlOrderRepository
from app.infrastructure.rate_limit.sliding_window import SlidingWindowRateLimiter
from app.infrastructure.system_clock import SystemClock
from app.interfaces.api.container import Container
from app.interfaces.api.errors import (
    batch_not_found_handler,
    courier_request_handler,
    order_not_found_handler,
    order_not_trackable_handler,
    order_persistence_handler,
    unsupported_courier_handler,
    validation_handler,
)
from app.interfaces.api.middleware import RateLimitMiddleware
from app.interfaces.api.routers import health, orders

_DESCRIPTION = """
HTTP API organised in clean-architecture layers.

Rate limits follow draft-ietf-httpapi-ratelimit-headers. Every limited
response includes `RateLimit-Policy` and `RateLimit`. A client that
exceeds quota receives `429` with `Retry-After` and
`application/problem+json`.

Two policies are enforced together:

- `burst` — short window
- `sustained` — long window

A request is counted only when both policies still have quota. Send
`X-API-Key` to partition quota by caller. Without that header, quota is
partitioned by client address.
""".strip()


def create_app(
    settings: Settings | None = None,
    rate_limiter: RateLimiter | None = None,
    courier: CourierGateway | None = None,
    courier_settings: CourierSettings | None = None,
) -> FastAPI:
    """Build the FastAPI app. Callers can pass their own courier adapter."""
    settings = settings or Settings()
    courier_settings = courier_settings or CourierSettings()
    rate_limiter = rate_limiter or _limiter_from_settings(settings)
    clock = SystemClock()
    owned_http: httpx.AsyncClient | None = None
    if courier is None:
        owned_http = httpx.AsyncClient(timeout=30.0)
        courier = UrbaneboltCourier(courier_settings, owned_http, clock)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if owned_http is not None:
            await owned_http.aclose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        summary="Clean-architecture API with standard HTTP rate limiting.",
        description=_DESCRIPTION,
        lifespan=lifespan,
    )
    order_repository = MysqlOrderRepository(courier_settings.database_url)
    app.state.container = Container(
        settings=settings,
        rate_limiter=rate_limiter,
        create_order=CreateOrder(courier, courier_settings.courier_partner, order_repository),
        track_order=TrackOrder(order_repository, courier),
        cancel_order=CancelOrder(order_repository, courier),
        submit_bulk=SubmitBulkOrders(
            courier,
            courier_settings.courier_partner,
            order_repository,
            concurrency=courier_settings.bulk_concurrency,
        ),
    )

    app.add_exception_handler(BatchNotFound, batch_not_found_handler)
    app.add_exception_handler(UnsupportedCourier, unsupported_courier_handler)
    app.add_exception_handler(OrderNotFound, order_not_found_handler)
    app.add_exception_handler(OrderNotTrackable, order_not_trackable_handler)
    app.add_exception_handler(CourierRequestError, courier_request_handler)
    app.add_exception_handler(OrderPersistenceError, order_persistence_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=rate_limiter,
        enabled=settings.rate_limit_enabled,
        trust_proxy=settings.trust_proxy,
    )
    app.include_router(health.router)
    app.include_router(orders.router)
    return app


def _limiter_from_settings(settings: Settings) -> SlidingWindowRateLimiter:
    policies = tuple(
        QuotaPolicy(name, quota, window) for name, quota, window in settings.quota_policies()
    )
    return SlidingWindowRateLimiter(policies)
