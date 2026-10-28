"""Accept a manifest batch and book each new order in the background."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.application.ports.courier import CourierGateway
from app.application.use_cases.create_order import _identifiers
from app.domain.entities.order import Order
from app.domain.exceptions import BatchNotFound, CourierRequestError, OrderPersistenceError
from app.domain.ports.order_repository import OrderRecord, OrderRepository

logger = logging.getLogger(__name__)

_REASON_LIMIT = 180


@dataclass(frozen=True, slots=True)
class BulkOrderOutcome:
    """One order inside a bulk batch."""

    order_id: str
    courier_partner: str
    status: str
    reason: str | None = None
    awb_number: str | None = None


@dataclass(frozen=True, slots=True)
class BulkBatchStatus:
    """Batch progress returned by accept and by the status read."""

    batch_id: str
    status: str
    total_orders: int
    succeeded: int
    failed: int
    pending: int
    results: list[BulkOrderOutcome]


@dataclass(frozen=True, slots=True)
class BulkSubmission:
    """One order from the bulk request, with the JSON that was stored."""

    order: Order
    request_payload: dict[str, Any]


class SubmitBulkOrders:
    """Reserve a batch, then manifest orders concurrently."""

    def __init__(
        self,
        courier: CourierGateway,
        partner_name: str,
        orders: OrderRepository,
        *,
        concurrency: int = 10,
    ) -> None:
        self._courier = courier
        self._partner_name = partner_name.strip()
        self._orders = orders
        self._concurrency = concurrency
        self._lock = asyncio.Lock()

    async def accept(self, submissions: list[BulkSubmission]) -> BulkBatchStatus:
        batch_id = str(uuid4())
        summary = _encode([], total=len(submissions))
        await self._orders.create_batch(batch_id, len(submissions), summary)
        return _status(batch_id, "PROCESSING", len(submissions), [])

    async def process(self, batch_id: str, submissions: list[BulkSubmission]) -> None:
        results: list[dict[str, Any]] = []
        jobs: list[BulkSubmission] = []
        seen: set[str] = set()
        for submission in submissions:
            order_id = submission.order.order_id
            partner = submission.order.courier_partner
            if order_id in seen:
                results.append(
                    _outcome(order_id, partner, "failed", "Duplicate order_id in this batch")
                )
                continue
            seen.add(order_id)
            jobs.append(submission)

        try:
            await self._publish(batch_id, "PROCESSING", results, len(submissions))
            semaphore = asyncio.Semaphore(self._concurrency)

            async def run(submission: BulkSubmission) -> None:
                async with semaphore:
                    outcome = await self._one(submission)
                async with self._lock:
                    results.append(outcome)
                    await self._publish(batch_id, "PROCESSING", results, len(submissions))

            await asyncio.gather(*(run(submission) for submission in jobs))
            await self._publish(batch_id, _final_status(results), results, len(submissions))
        except Exception:
            logger.exception("bulk batch_id=%s stopped", batch_id)
            status = "PROCESSING" if len(results) < len(submissions) else _final_status(results)
            await self._publish(batch_id, status, results, len(submissions))

    async def get(self, batch_id: str) -> BulkBatchStatus:
        record = await self._orders.get_batch(batch_id)
        if record is None:
            raise BatchNotFound(batch_id)
        stored = _decode(record.summary)
        return _status(record.batch_id, record.status, record.total_orders, stored)

    async def _one(self, submission: BulkSubmission) -> dict[str, Any]:
        order = submission.order
        order_id = order.order_id
        partner = order.courier_partner
        if not self._partner_name or partner.lower() != self._partner_name.lower():
            return _outcome(order_id, partner, "failed", f"Courier partner {partner!r} is not supported")

        request_payload = json.dumps(submission.request_payload, ensure_ascii=False, default=str)
        try:
            claim = await self._orders.claim(order_id, partner, request_payload)
        except OrderPersistenceError as exc:
            return _outcome(order_id, partner, "failed", str(exc))

        if claim.state == "exists" and claim.record is not None:
            return _outcome(
                order_id,
                claim.record.courier_partner,
                "succeeded",
                "Order already submitted",
                claim.record.awb_number,
            )
        if claim.state == "cancelled":
            return _outcome(order_id, partner, "failed", "Order was already cancelled")
        if claim.state != "claimed":
            return _outcome(order_id, partner, "failed", "Order is already being processed")

        try:
            body = await self._courier.create_shipment(order)
        except CourierRequestError as exc:
            await self._store(
                order_id,
                partner,
                "FAILED",
                submission.request_payload,
                exc.courier_response or {"detail": str(exc)},
            )
            return _outcome(order_id, partner, "failed", str(exc))
        except Exception:
            logger.exception("manifest failed for order_id=%s", order_id)
            await self._store(order_id, partner, "FAILED", submission.request_payload, {"detail": "Manifest failed"})
            return _outcome(order_id, partner, "failed", "Manifest failed")

        await self._store(order_id, partner, "MANIFESTED", submission.request_payload, body)
        awb_number, _courier_order_id = _identifiers(body, order_id)
        return _outcome(order_id, partner, "succeeded", None, awb_number)

    async def _store(
        self,
        order_id: str,
        partner: str,
        status: str,
        request_payload: dict[str, Any],
        response_payload: Any,
    ) -> None:
        awb_number, courier_order_id = _identifiers(response_payload, order_id)
        record = OrderRecord(
            id=str(uuid4()),
            order_id=order_id,
            courier_partner=partner,
            status=status,
            raw_request_payload=json.dumps(request_payload, ensure_ascii=False, default=str),
            raw_response_payload=json.dumps(response_payload, ensure_ascii=False, default=str),
            courier_order_id=courier_order_id,
            awb_number=awb_number,
        )
        try:
            await self._orders.save(record)
        except OrderPersistenceError:
            logger.exception("failed to store bulk result for order_id=%s", order_id)

    async def _publish(
        self,
        batch_id: str,
        status: str,
        results: list[dict[str, Any]],
        total: int,
    ) -> None:
        try:
            await self._orders.update_batch(batch_id, status, _encode(results, total=total))
        except OrderPersistenceError:
            logger.exception("failed to publish batch_id=%s", batch_id)


def _final_status(results: list[dict[str, Any]]) -> str:
    if results and all(item["status"] == "succeeded" for item in results):
        return "COMPLETED"
    return "COMPLETED_WITH_ERRORS"


def _outcome(
    order_id: str,
    courier_partner: str,
    status: str,
    reason: str | None,
    awb_number: str | None = None,
) -> dict[str, Any]:
    if reason:
        reason = reason[:_REASON_LIMIT]
    return {
        "order_id": order_id,
        "courier_partner": courier_partner,
        "status": status,
        "reason": reason,
        "awb_number": awb_number,
    }


def _encode(results: list[dict[str, Any]], *, total: int) -> str:
    failed = sum(1 for item in results if item["status"] == "failed")
    succeeded = sum(1 for item in results if item["status"] == "succeeded")
    body = {
        "succeeded": succeeded,
        "failed": failed,
        "pending": max(total - len(results), 0),
        "results": results,
    }
    return json.dumps(body, ensure_ascii=False, default=str)


def _decode(summary: str) -> list[dict[str, Any]]:
    try:
        body = json.loads(summary or "{}")
    except json.JSONDecodeError:
        return []
    results = body.get("results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _status(batch_id: str, status: str, total: int, results: list[dict[str, Any]]) -> BulkBatchStatus:
    outcomes = [
        BulkOrderOutcome(
            order_id=str(item.get("order_id") or ""),
            courier_partner=str(item.get("courier_partner") or ""),
            status=str(item.get("status") or "failed"),
            reason=item.get("reason"),
            awb_number=item.get("awb_number"),
        )
        for item in results
    ]
    failed = sum(1 for item in outcomes if item.status == "failed")
    succeeded = sum(1 for item in outcomes if item.status == "succeeded")
    return BulkBatchStatus(
        batch_id=batch_id,
        status=status,
        total_orders=total,
        succeeded=succeeded,
        failed=failed,
        pending=max(total - len(outcomes), 0),
        results=outcomes,
    )
