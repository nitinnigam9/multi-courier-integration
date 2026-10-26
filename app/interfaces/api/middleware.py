"""ASGI middleware that enforces quota before the route runs."""

import hashlib
import logging
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.application.ports.rate_limiter import RateLimiter
from app.interfaces.api.errors import QUOTA_EXCEEDED, problem_response
from app.interfaces.api.rate_limit_headers import rate_limit_headers

logger = logging.getLogger(__name__)

_EXEMPT_PATHS = {"/health", "/openapi.json", "/favicon.ico"}
_EXEMPT_PREFIXES = ("/docs", "/redoc")


class RateLimitMiddleware:
    """Apply the limiter and attach standard rate-limit headers."""

    def __init__(
        self,
        app: ASGIApp,
        limiter: RateLimiter,
        *,
        enabled: bool = True,
        trust_proxy: bool = False,
    ) -> None:
        self.app = app
        self.limiter = limiter
        self.enabled = enabled
        self.trust_proxy = trust_proxy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.enabled or _is_exempt(scope):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        partition = client_partition(request, trust_proxy=self.trust_proxy)
        decision = await self.limiter.consume(partition)
        headers = rate_limit_headers(decision)

        if not decision.allowed:
            logger.info(
                "rate limit exceeded partition=%s policies=%s",
                partition,
                ",".join(decision.violated),
            )
            response = problem_response(
                status_code=429,
                type_=QUOTA_EXCEEDED,
                title="Request cannot be satisfied as assigned quota has been exceeded",
                detail=f"Quota exceeded for: {', '.join(decision.violated)}.",
                instance=request.url.path,
                headers={**headers, "Retry-After": str(decision.retry_after_seconds)},
                extensions={"violated-policies": list(decision.violated)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, _send_with_headers(send, headers))


def client_partition(request: Request, *, trust_proxy: bool) -> str:
    """Build an opaque partition key from the API key, or from the client address."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        return _digest("key", api_key)

    host = request.client.host if request.client is not None else ""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            host = forwarded.split(",", 1)[0].strip()
    return _digest("ip", host or "unknown")


def _digest(kind: str, value: str) -> str:
    material = f"{kind}:{value}".encode()
    return f"{kind}:{hashlib.sha256(material).hexdigest()[:32]}"


def _is_exempt(scope: Scope) -> bool:
    if scope.get("method") == "OPTIONS":
        return True
    path = scope.get("path", "")
    if path in _EXEMPT_PATHS:
        return True
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in _EXEMPT_PREFIXES)


def _send_with_headers(
    send: Callable[[Message], Awaitable[None]],
    headers: dict[str, str],
) -> Callable[[Message], Awaitable[None]]:
    async def send_with_headers(message: Message) -> None:
        if message["type"] == "http.response.start":
            raw = list(message.get("headers", []))
            existing = {name.lower() for name, _ in raw}
            for name, value in headers.items():
                encoded = name.lower().encode("latin-1")
                if encoded not in existing:
                    raw.append((encoded, value.encode("latin-1")))
            message["headers"] = raw
        await send(message)

    return send_with_headers
