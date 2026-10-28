"""Urbane Bolt courier adapter.

Login is POST {origin}/api/v1/auth/getToken/. The token from that response is
sent as a Bearer token to POST {origin}/api/v1/services/manifest/.
"""

import asyncio
import logging
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from app.domain.entities.order import Order, Party
from app.domain.exceptions import CourierRequestError
from app.domain.ports.clock import Clock
from app.infrastructure.config import CourierSettings

logger = logging.getLogger(__name__)

_TOKEN_KEYS = ("token", "access_token", "access", "jwt", "key", "auth_token")


class UrbaneboltCourier:
    """Logs in to Urbane Bolt and manifests one shipment per order."""

    def __init__(self, settings: CourierSettings, http: httpx.AsyncClient, clock: Clock) -> None:
        self._settings = settings
        self._http = http
        self._clock = clock
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def create_shipment(self, order: Order) -> Any:
        shipment = manifest_shipment(
            order,
            customer_code=self._required("courier_customer_code", self._settings.courier_customer_code),
            service_type=self._settings.courier_service_type.strip() or "SDD",
            invoice_date=self._clock.now().date(),
        )
        try:
            response = await self._manifest([shipment], force_login=False)
            if response.status_code == 401:
                response = await self._manifest([shipment], force_login=True)
            body = self._response_body(response)
            if response.status_code >= 400 or _indicates_failure(body):
                raise self._upstream_error("manifest", response.status_code, body, order.order_id)
        except CourierRequestError as exc:
            exc.order_id = exc.order_id or order.order_id
            raise
        logger.info("manifested order_id=%s status=%s", order.order_id, response.status_code)
        return body

    async def submit_manifest(self, shipment: dict[str, Any]) -> Any:
        order_id = str(shipment.get("orderNumber") or "")
        response = await self._manifest([shipment], force_login=False)
        if response.status_code == 401:
            response = await self._manifest([shipment], force_login=True)
        body = self._response_body(response)
        if response.status_code >= 400 or _indicates_failure(body):
            raise self._upstream_error("manifest", response.status_code, body, order_id or None)
        logger.info("manifested order_id=%s status=%s", order_id or "-", response.status_code)
        return body

    async def track(self, awb: str) -> Any:
        response = await self._tracking(awb, force_login=False)
        if response.status_code == 401:
            response = await self._tracking(awb, force_login=True)
        body = self._response_body(response)
        if response.status_code >= 400 or _indicates_failure(body):
            raise self._upstream_error("tracking", response.status_code, body, None)
        logger.info("tracked awb=%s status=%s", awb, response.status_code)
        return body

    async def cancel(self, awb: str) -> Any:
        response = await self._cancel(awb, force_login=False)
        if response.status_code == 401:
            response = await self._cancel(awb, force_login=True)
        body = self._response_body(response)
        if response.status_code >= 400 or _indicates_failure(body):
            raise self._upstream_error("cancel", response.status_code, body, None)
        logger.info("cancelled awb=%s status=%s", awb, response.status_code)
        return body

    async def _cancel(self, awb: str, *, force_login: bool) -> httpx.Response:
        token = await self._access_token(force=force_login)
        return await self._send(
            "POST",
            "cancel",
            _url(self._settings.courier_partner_url, self._settings.courier_cancel_path),
            json={"awbs": awb},
            headers={"Authorization": f"Bearer {token}"},
        )

    async def _tracking(self, awb: str, *, force_login: bool) -> httpx.Response:
        token = await self._access_token(force=force_login)
        return await self._send(
            "GET",
            "tracking",
            _url(self._settings.courier_partner_url, self._settings.courier_tracking_path),
            params={"awb": awb},
            headers={"Authorization": f"Bearer {token}"},
        )

    async def _manifest(self, body: list[dict[str, Any]], *, force_login: bool) -> httpx.Response:
        token = await self._access_token(force=force_login)
        return await self._send(
            "POST",
            "manifest",
            _url(self._settings.courier_partner_url, self._settings.courier_manifest_path),
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def _access_token(self, *, force: bool) -> str:
        async with self._lock:
            if self._token and not force:
                return self._token
            username = self._required("courier_username", self._settings.courier_username)
            password = self._required("courier_password", self._settings.courier_password)
            response = await self._send(
                "POST",
                "login",
                _url(self._settings.courier_partner_url, self._settings.courier_login_path),
                json={"username": username, "password": password},
                headers=self._csrf_headers(),
            )
            body = self._response_body(response)
            if response.status_code >= 400 or _indicates_failure(body):
                raise self._upstream_error("login", response.status_code, body, None)
            try:
                self._token = _extract_token(body)
            except CourierRequestError:
                raise self._upstream_error("login", response.status_code, body, None) from None
            return self._token

    async def _send(self, method: str, operation: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise CourierRequestError(
                f"Courier {operation} timed out",
                operation=operation,
                status_code=504,
            ) from exc
        except httpx.RequestError as exc:
            reason = _scrub_text(str(exc), self._settings.courier_password)
            raise CourierRequestError(
                f"Courier {operation} could not be reached at {url}: {reason}",
                operation=operation,
                status_code=503,
            ) from exc

    def _csrf_headers(self) -> dict[str, str]:
        token = self._settings.courier_csrf_token.strip()
        if not token:
            return {}
        return {"Cookie": f"csrftoken={token}"}

    def _required(self, name: str, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise CourierRequestError(f"{name} is not configured")
        if name == "courier_customer_code":
            return cleaned
        if name != "courier_partner_url" and not self._settings.courier_partner_url.strip():
            raise CourierRequestError("courier_partner_url is not configured")
        return cleaned

    def _response_body(self, response: httpx.Response) -> Any:
        return _scrub(_json_body(response), self._settings.courier_password)

    def _upstream_error(
        self,
        operation: str,
        courier_status: int,
        body: Any,
        order_id: str | None,
    ) -> CourierRequestError:
        logical_failure = courier_status < 400
        fallback = f"Courier {operation} failed with status {courier_status}"
        detail = _scrub_text(_message(body, fallback), self._settings.courier_password)
        logger.warning(
            "courier %s failed status=%s order_id=%s",
            operation,
            courier_status,
            order_id or "-",
        )
        return CourierRequestError(
            detail,
            operation=operation,
            status_code=_client_status(operation, courier_status, logical=logical_failure),
            courier_status=courier_status,
            courier_response=body,
            order_id=order_id,
        )


def manifest_shipment(
    order: Order,
    *,
    customer_code: str,
    service_type: str,
    invoice_date: date,
) -> dict[str, Any]:
    """Map an order onto one Urbane Bolt manifest record."""
    pay_mode, collectable = _payment(order.package.payment_mode, order.package.declared_value)
    pickup = _party_fields("shpr", order.pickup, address_type="Seller")
    delivery = _party_fields("cons", order.delivery, address_type="Home")
    returns = _party_fields("rtn", order.pickup, address_type="Seller")
    return {
        "customerCode": customer_code,
        "orderNumber": order.order_id,
        "declaredValue": _money(order.package.declared_value),
        "itemDescription": ", ".join(item.name.strip() for item in order.items),
        "collectableValue": collectable,
        "height": _measure(order.package.dimensions.height_cm),
        "length": _measure(order.package.dimensions.length_cm),
        "pieces": 1,
        "weight": _measure(order.package.weight_kg),
        "breadth": _measure(order.package.dimensions.width_cm),
        "serviceType": service_type,
        "payMode": pay_mode,
        **returns,
        **delivery,
        **pickup,
        "invoiceNumber": order.order_id,
        "invoiceDate": invoice_date.isoformat(),
        "invoiceValue": _money(order.package.declared_value),
        "itemQuantity": sum(item.quantity for item in order.items),
    }


def _party_fields(prefix: str, party: Party, *, address_type: str) -> dict[str, Any]:
    lines = [party.address_line1.strip(), party.address_line2.strip()]
    address = ", ".join(line for line in lines if line)
    return {
        f"{prefix}Name": party.contact_name.strip(),
        f"{prefix}Mobile": _digits(party.phone),
        f"{prefix}Email": party.email.strip(),
        f"{prefix}Address": address,
        f"{prefix}AddressType": address_type,
        f"{prefix}City": party.city.strip(),
        f"{prefix}State": party.state.strip(),
        f"{prefix}Pincode": _digits(party.pincode),
        f"{prefix}Country": party.country.strip(),
    }


def _payment(mode: str, declared_value: Decimal) -> tuple[str, int | float]:
    normalized = mode.strip().upper()
    if normalized == "COD":
        return "COD", _money(declared_value)
    if normalized in {"PREPAID", "PPD"}:
        return "PPD", 0
    raise CourierRequestError(f"payment mode {mode!r} is not supported")


def _digits(value: str) -> int:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not digits:
        raise CourierRequestError("A phone number or pincode is missing")
    return int(digits)


def _money(value: Decimal) -> int | float:
    if value == value.to_integral():
        return int(value)
    return float(value)


def _measure(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return float(value)


def _url(base: str, path: str) -> str:
    root = base.strip().rstrip("/")
    if not root:
        raise CourierRequestError("courier_partner_url is not configured")
    lowered = root.lower()
    if lowered.endswith("/api/v1"):
        root = root[: -len("/api/v1")]
    elif lowered.endswith("/v1"):
        root = root[: -len("/v1")]
    return f"{root}/{path.lstrip('/')}"


def _json_body(response: httpx.Response) -> Any:
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text}


def _extract_token(body: Any, depth: int = 0) -> str:
    if depth > 4:
        raise CourierRequestError("Courier login response did not include a token")
    if isinstance(body, str) and body.strip():
        return body.strip()
    if isinstance(body, dict):
        for key in _TOKEN_KEYS:
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("data", "result", "payload"):
            nested = body.get(key)
            if isinstance(nested, (dict, str)) and nested is not body:
                try:
                    return _extract_token(nested, depth + 1)
                except CourierRequestError:
                    continue
    raise CourierRequestError("Courier login response did not include a token")


_SUCCESS_FLAGS = {"true", "1", "success", "successful", "ok", "passed", "booked", "created", "manifested"}
_FAILURE_FLAGS = {"false", "0", "failed", "failure", "error", "fail", "rejected", "invalid"}
_FLAG_KEYS = ("success", "Success", "status", "Status", "statusCode", "StatusCode")
_MESSAGE_KEYS = (
    "message",
    "Message",
    "detail",
    "Detail",
    "errorMessage",
    "error_message",
    "remarks",
    "remark",
    "Remark",
)


def _client_status(operation: str, courier_status: int, *, logical: bool) -> int:
    if operation == "login":
        return 502
    if logical or courier_status < 400:
        return 422
    if courier_status in {401, 403}:
        return 502
    if courier_status in {400, 404, 409, 422, 429}:
        return courier_status
    if 400 <= courier_status < 500:
        return 400
    if courier_status == 504:
        return 504
    return 502


def _indicates_failure(body: Any, *, depth: int = 0) -> bool:
    if depth > 3:
        return False
    if isinstance(body, list):
        records = [item for item in body if isinstance(item, (dict, list))]
        return bool(records) and all(_indicates_failure(item, depth=depth + 1) for item in records)
    if not isinstance(body, dict):
        return False
    flags: list[str | None] = []
    for key in _FLAG_KEYS:
        if key not in body:
            continue
        value = body[key]
        if isinstance(value, int) and value >= 400:
            return True
        if isinstance(value, int) and 200 <= value < 300:
            return False
        flags.append(_flag(value))
    if any(flag in _SUCCESS_FLAGS for flag in flags):
        return False
    if any(flag in _FAILURE_FLAGS for flag in flags):
        return True
    for key in ("error", "Error", "errors", "Errors"):
        value = body.get(key)
        if value not in (None, "", [], {}):
            return True
    for key in ("data", "result", "response", "payload"):
        nested = body.get(key)
        if isinstance(nested, (dict, list)) and _indicates_failure(nested, depth=depth + 1):
            return True
    return False


def _flag(value: Any) -> str | None:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and value in {0, 1}:
        return str(value)
    if isinstance(value, str):
        return value.strip().lower()
    return None


def _message(body: Any, fallback: str) -> str:
    text = _message_text(body)
    if not text:
        return fallback
    if len(text) > 1000:
        return text[:1000] + "..."
    return text


def _message_text(body: Any) -> str:
    if isinstance(body, str) and body.strip():
        return body.strip()
    if isinstance(body, list):
        parts = [text for item in body if (text := _message_text(item))]
        return "; ".join(parts)
    if not isinstance(body, dict):
        return ""
    raw = body.get("raw")
    if isinstance(raw, str) and raw.strip() and len(body) == 1:
        return raw.strip()
    for key in _MESSAGE_KEYS:
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("error", "Error"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            text = _message_text(value)
            if text:
                return text
    for key in ("errors", "Errors"):
        value = body.get(key)
        if isinstance(value, list):
            parts = [text for item in value if (text := _message_text(item))]
            if parts:
                return "; ".join(parts)
    for key in ("data", "result", "response", "payload"):
        nested = body.get(key)
        if isinstance(nested, (dict, list)):
            text = _message_text(nested)
            if text:
                return text
    return ""


def _scrub(value: Any, secret: str) -> Any:
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, "***")
    if isinstance(value, list):
        return [_scrub(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item, secret) for key, item in value.items()}
    return value


def _scrub_text(value: str, secret: str) -> str:
    if secret:
        return value.replace(secret, "***")
    return value
