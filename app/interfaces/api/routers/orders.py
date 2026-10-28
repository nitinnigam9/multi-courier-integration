"""Order routes."""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from pydantic import Field

from app.application.use_cases.cancel_order import CancelOrder
from app.application.use_cases.create_order import CreateOrder
from app.application.use_cases.submit_bulk_orders import BulkSubmission, SubmitBulkOrders
from app.application.use_cases.track_order import TrackOrder
from app.interfaces.api.dependencies import (
    get_cancel_order,
    get_create_order,
    get_submit_bulk,
    get_track_order,
)
from app.interfaces.api.schemas.bulk import BulkBatchResponse, BulkOrderResult
from app.interfaces.api.schemas.order import (
    CancelOrderRequest,
    OrderAccepted,
    OrderCancelled,
    OrderCreate,
    OrderTracking,
)

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])

_BULK_DESCRIPTION = """
Returns `202` and a `batch_id` immediately. Manifest calls run in this process
after the response, concurrently, with a bounded number of calls in flight.
The request does not call the courier once per order in sequence.

Poll `GET /api/v1/orders/bulk/{batch_id}` for per-order success or failure.
`results` lists finished orders. `pending` counts orders still in flight.
`succeeded` and `failed` are the totals so far.

The body is an array of the same order objects as `POST /api/v1/orders`:
`order_id`, `courier_partner`, `pickup_details`, `delivery_details`,
`package_details`, and `items`. Each order is mapped to the courier manifest
and posted to `/api/v1/services/manifest/`. `order_id` is the idempotency key:
a second submit does not create another shipment. An order that previously
failed is sent again. A different `courier_partner` on one row fails that row
only.

Trade-offs versus a blocking response or a stream:
- The client is not held open for the slowest courier call, so a proxy timeout
  cannot abandon the batch.
- This response does not contain the final results, and results are not streamed.
  The client polls.
- Work is in-process. If the API process stops, a batch can stay `PROCESSING`
  and is not resumed. A separate queue would survive restarts but needs more
  infrastructure.
- Each order is its own manifest request so a rejection stays attached to that
  order. One combined array would be fewer HTTP calls, but a partner error is
  harder to split into per-order reasons.
"""


@router.post(
    "/bulk",
    response_model=BulkBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    description=_BULK_DESCRIPTION,
)
async def create_bulk_orders(
    orders: Annotated[list[OrderCreate], Field(min_length=1, max_length=100)],
    background_tasks: BackgroundTasks,
    use_case: Annotated[SubmitBulkOrders, Depends(get_submit_bulk)],
) -> BulkBatchResponse:
    submissions = [
        BulkSubmission(order=item.to_order(), request_payload=item.model_dump(mode="json"))
        for item in orders
    ]
    accepted = await use_case.accept(submissions)
    background_tasks.add_task(use_case.process, accepted.batch_id, submissions)
    return _batch_response(accepted)


@router.get("/bulk/{batch_id}", response_model=BulkBatchResponse)
async def get_bulk_batch(
    batch_id: str,
    use_case: Annotated[SubmitBulkOrders, Depends(get_submit_bulk)],
) -> BulkBatchResponse:
    return _batch_response(await use_case.get(batch_id))


@router.post("", response_model=OrderAccepted, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderCreate,
    use_case: Annotated[CreateOrder, Depends(get_create_order)],
) -> OrderAccepted:
    created = await use_case.execute(payload.to_order(), payload.model_dump(mode="json"))
    return OrderAccepted(
        order_id=created.order_id,
        courier_partner=created.courier_partner,
        manifest=created.manifest,
    )


@router.get("/{order_id}/track", response_model=OrderTracking)
async def track_order(
    order_id: str,
    courier_partner: Annotated[str, Query(min_length=1, max_length=50)],
    use_case: Annotated[TrackOrder, Depends(get_track_order)],
) -> OrderTracking:
    tracked = await use_case.execute(order_id, courier_partner)
    return OrderTracking(
        order_id=tracked.order_id,
        awb_number=tracked.awb_number,
        courier_partner=tracked.courier_partner,
        tracking=tracked.tracking,
    )


@router.post("/{order_id}/cancel", response_model=OrderCancelled)
async def cancel_order(
    order_id: str,
    payload: CancelOrderRequest,
    use_case: Annotated[CancelOrder, Depends(get_cancel_order)],
) -> OrderCancelled:
    cancelled = await use_case.execute(order_id, payload.courier_partner)
    return OrderCancelled(
        order_id=cancelled.order_id,
        awb_number=cancelled.awb_number,
        courier_partner=cancelled.courier_partner,
        cancellation=cancelled.cancellation,
    )


def _batch_response(batch: Any) -> BulkBatchResponse:
    return BulkBatchResponse(
        batch_id=batch.batch_id,
        status=batch.status,
        total_orders=batch.total_orders,
        succeeded=batch.succeeded,
        failed=batch.failed,
        pending=batch.pending,
        results=[
            BulkOrderResult(
                order_id=item.order_id,
                courier_partner=item.courier_partner,
                status=item.status,
                reason=item.reason,
                awb_number=item.awb_number,
            )
            for item in batch.results
        ],
    )
