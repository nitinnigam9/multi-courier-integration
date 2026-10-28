"""RFC 9457 problem details for API errors."""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    BatchNotFound,
    CourierRequestError,
    OrderNotFound,
    OrderNotTrackable,
    OrderPersistenceError,
    UnsupportedCourier,
)

QUOTA_EXCEEDED = "https://iana.org/assignments/http-problem-types#quota-exceeded"
PROBLEM_MEDIA_TYPE = "application/problem+json"


def problem_response(
    *,
    status_code: int,
    title: str,
    detail: str,
    instance: str,
    type_: str = "about:blank",
    headers: dict[str, str] | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": type_,
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
    }
    if extensions:
        body.update(extensions)
    return JSONResponse(
        body,
        status_code=status_code,
        headers=headers,
        media_type=PROBLEM_MEDIA_TYPE,
    )


async def batch_not_found_handler(request: Request, exc: BatchNotFound) -> JSONResponse:
    return problem_response(
        status_code=404,
        title="Batch not found",
        detail=str(exc),
        instance=request.url.path,
    )


async def order_not_found_handler(request: Request, exc: OrderNotFound) -> JSONResponse:
    return problem_response(
        status_code=404,
        title="Order not found",
        detail=str(exc),
        instance=request.url.path,
    )


async def order_not_trackable_handler(request: Request, exc: OrderNotTrackable) -> JSONResponse:
    return problem_response(
        status_code=422,
        title="Order has no airway bill",
        detail=str(exc),
        instance=request.url.path,
    )


async def unsupported_courier_handler(request: Request, exc: UnsupportedCourier) -> JSONResponse:
    return problem_response(
        status_code=422,
        title="Unsupported courier",
        detail=str(exc),
        instance=request.url.path,
    )


async def courier_request_handler(request: Request, exc: CourierRequestError) -> JSONResponse:
    extensions: dict[str, Any] = {"courier_operation": exc.operation}
    if exc.order_id:
        extensions["order_id"] = exc.order_id
    if exc.courier_status is not None:
        extensions["courier_status"] = exc.courier_status
    if exc.courier_response is not None:
        extensions["courier_response"] = exc.courier_response
    return problem_response(
        status_code=exc.status_code,
        title=_courier_title(exc.status_code),
        detail=str(exc),
        instance=request.url.path,
        extensions=extensions,
    )


async def order_persistence_handler(request: Request, exc: OrderPersistenceError) -> JSONResponse:
    extensions: dict[str, Any] = {}
    if exc.manifest is not None:
        extensions["manifest"] = exc.manifest
    return problem_response(
        status_code=503,
        title="Order could not be saved",
        detail=str(exc),
        instance=request.url.path,
        extensions=extensions or None,
    )


def _courier_title(status_code: int) -> str:
    titles = {
        400: "Courier rejected the shipment",
        404: "Courier resource was not found",
        409: "Courier rejected the shipment",
        422: "Courier rejected the shipment",
        429: "Courier rate limit exceeded",
        503: "Courier service is unavailable",
        504: "Courier request timed out",
    }
    return titles.get(status_code, "Courier request failed")


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"loc": ".".join(str(part) for part in error["loc"]), "msg": error["msg"]}
        for error in exc.errors()
    ]
    return problem_response(
        status_code=422,
        title="Unprocessable Entity",
        detail="Request validation failed.",
        instance=request.url.path,
        extensions={"errors": errors},
    )
