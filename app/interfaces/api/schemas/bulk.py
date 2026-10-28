"""Bulk batch status."""

from typing import Literal

from pydantic import BaseModel


class BulkOrderResult(BaseModel):
    """Success or failure for a single order in the batch."""

    order_id: str
    courier_partner: str
    status: Literal["succeeded", "failed"]
    reason: str | None = None
    awb_number: str | None = None


class BulkBatchResponse(BaseModel):
    """Batch accepted for background processing, or its current progress."""

    batch_id: str
    status: str
    total_orders: int
    succeeded: int
    failed: int
    pending: int
    results: list[BulkOrderResult]
