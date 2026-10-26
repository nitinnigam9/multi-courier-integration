"""RFC 9457 problem details for API errors."""

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.exceptions import InvalidItem, ItemNotFound

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


async def item_not_found_handler(request: Request, exc: ItemNotFound) -> JSONResponse:
    return problem_response(
        status_code=404,
        title="Item not found",
        detail=str(exc),
        instance=request.url.path,
    )


async def invalid_item_handler(request: Request, exc: InvalidItem) -> JSONResponse:
    return problem_response(
        status_code=422,
        title="Invalid item",
        detail=str(exc),
        instance=request.url.path,
    )


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
