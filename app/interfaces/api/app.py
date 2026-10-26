"""Composition root for the HTTP application."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.application.ports.rate_limiter import QuotaPolicy, RateLimiter
from app.application.use_cases.items import CreateItem, GetItem, ListItems
from app.domain.exceptions import InvalidItem, ItemNotFound
from app.domain.ports.item_repository import ItemRepository
from app.infrastructure.config import Settings
from app.infrastructure.persistence.memory_item_repository import MemoryItemRepository
from app.infrastructure.rate_limit.sliding_window import SlidingWindowRateLimiter
from app.infrastructure.system_clock import SystemClock
from app.interfaces.api.container import Container
from app.interfaces.api.errors import (
    invalid_item_handler,
    item_not_found_handler,
    validation_handler,
)
from app.interfaces.api.middleware import RateLimitMiddleware
from app.interfaces.api.routers import health, items

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
    repository: ItemRepository | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    """Build the FastAPI app. Tests pass their own repository and limiter."""
    settings = settings or Settings()
    repository = repository or MemoryItemRepository()
    rate_limiter = rate_limiter or _limiter_from_settings(settings)
    clock = SystemClock()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        summary="Clean-architecture API with standard HTTP rate limiting.",
        description=_DESCRIPTION,
    )
    app.state.container = Container(
        settings=settings,
        repository=repository,
        rate_limiter=rate_limiter,
        create_item=CreateItem(repository, clock),
        get_item=GetItem(repository),
        list_items=ListItems(repository),
    )

    app.add_exception_handler(ItemNotFound, item_not_found_handler)
    app.add_exception_handler(InvalidItem, invalid_item_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_middleware(
        RateLimitMiddleware,
        limiter=rate_limiter,
        enabled=settings.rate_limit_enabled,
        trust_proxy=settings.trust_proxy,
    )
    app.include_router(health.router)
    app.include_router(items.router)
    return app


def _limiter_from_settings(settings: Settings) -> SlidingWindowRateLimiter:
    policies = tuple(
        QuotaPolicy(name, quota, window) for name, quota, window in settings.quota_policies()
    )
    return SlidingWindowRateLimiter(policies)
