"""MySQL storage for orders."""

import asyncio
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.domain.exceptions import OrderPersistenceError
from app.domain.ports.order_repository import BatchRecord, ClaimResult, OrderRecord

logger = logging.getLogger(__name__)

_INSERT = text(
    """
    INSERT INTO orders (
        id,
        order_id,
        courier_partner,
        courier_order_id,
        awb_number,
        status,
        raw_request_payload,
        raw_response_payload
    ) VALUES (
        :id,
        :order_id,
        :courier_partner,
        :courier_order_id,
        :awb_number,
        :status,
        :raw_request_payload,
        :raw_response_payload
    )
    ON DUPLICATE KEY UPDATE
        courier_partner = VALUES(courier_partner),
        courier_order_id = VALUES(courier_order_id),
        awb_number = VALUES(awb_number),
        status = VALUES(status),
        raw_request_payload = VALUES(raw_request_payload),
        raw_response_payload = VALUES(raw_response_payload),
        updated_at = CURRENT_TIMESTAMP
    """
)


class MysqlOrderRepository:
    """Writes orders with the DATABASE_URL connection."""

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise OrderPersistenceError("DATABASE_URL is not configured")
        self._engine: Engine = create_engine(database_url, pool_pre_ping=True)

    async def save(self, record: OrderRecord) -> None:
        await asyncio.to_thread(self._save, record)

    def _save(self, record: OrderRecord) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    _INSERT,
                    {
                        "id": record.id,
                        "order_id": record.order_id,
                        "courier_partner": record.courier_partner,
                        "courier_order_id": record.courier_order_id,
                        "awb_number": record.awb_number,
                        "status": record.status,
                        "raw_request_payload": record.raw_request_payload,
                        "raw_response_payload": record.raw_response_payload,
                    },
                )
        except Exception as exc:
            logger.exception("failed to save order_id=%s", record.order_id)
            raise OrderPersistenceError(f"Order {record.order_id} could not be saved") from exc

    async def get(self, order_id: str, courier_partner: str) -> OrderRecord | None:
        return await asyncio.to_thread(self._get, order_id, courier_partner)

    def _get(self, order_id: str, courier_partner: str) -> OrderRecord | None:
        statement = text(
            """
            SELECT
                id,
                order_id,
                courier_partner,
                courier_order_id,
                awb_number,
                status,
                raw_request_payload,
                raw_response_payload
            FROM orders
            WHERE order_id = :order_id
              AND LOWER(courier_partner) = LOWER(:courier_partner)
            """
        )
        with self._engine.connect() as connection:
            row = connection.execute(
                statement,
                {"order_id": order_id, "courier_partner": courier_partner},
            ).mappings().first()
        if row is None:
            return None
        return OrderRecord(
            id=row["id"],
            order_id=row["order_id"],
            courier_partner=row["courier_partner"],
            status=row["status"],
            raw_request_payload=row["raw_request_payload"] or "",
            raw_response_payload=row["raw_response_payload"] or "",
            courier_order_id=row["courier_order_id"],
            awb_number=row["awb_number"],
        )

    async def save_tracking(self, order_id: str, status: str, raw_status_payload: str) -> None:
        await asyncio.to_thread(self._save_tracking, order_id, status, raw_status_payload)

    def _save_tracking(self, order_id: str, status: str, raw_status_payload: str) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO tracking_history (id, order_id, status, raw_status_payload)
                        VALUES (:id, :order_id, :status, :raw_status_payload)
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "order_id": order_id,
                        "status": status[:50],
                        "raw_status_payload": raw_status_payload,
                    },
                )
                connection.execute(
                    text(
                        """
                        UPDATE orders
                        SET status = :status, updated_at = CURRENT_TIMESTAMP
                        WHERE order_id = :order_id
                        """
                    ),
                    {"order_id": order_id, "status": status[:50]},
                )
        except Exception as exc:
            logger.exception("failed to save tracking for order_id=%s", order_id)
            raise OrderPersistenceError(f"Tracking for order {order_id} could not be saved") from exc

    async def claim(self, order_id: str, courier_partner: str, raw_request_payload: str) -> ClaimResult:
        return await asyncio.to_thread(self._claim, order_id, courier_partner, raw_request_payload)

    def _claim(self, order_id: str, courier_partner: str, raw_request_payload: str) -> ClaimResult:
        params = {
            "id": str(uuid4()),
            "order_id": order_id,
            "courier_partner": courier_partner,
            "raw_request_payload": raw_request_payload,
        }
        try:
            with self._engine.begin() as connection:
                connection.execute(_CLAIM, params)
            return ClaimResult("claimed")
        except IntegrityError:
            logger.info("order_id=%s is already stored", order_id)
        except Exception as exc:
            logger.exception("failed to claim order_id=%s", order_id)
            raise OrderPersistenceError(f"Order {order_id} could not be reserved") from exc

        for _ in range(2):
            try:
                with self._engine.begin() as connection:
                    updated = connection.execute(_RECLAIM_FAILED, params)
                    if updated.rowcount:
                        return ClaimResult("claimed")
                    row = connection.execute(_SELECT_BY_ORDER, {"order_id": order_id}).mappings().first()
            except Exception as exc:
                logger.exception("failed to read existing order_id=%s", order_id)
                raise OrderPersistenceError(f"Order {order_id} could not be reserved") from exc
            record = _record(row) if row is not None else None
            if record is not None and record.status == "FAILED" and not record.awb_number:
                continue
            return _classify_existing(record)
        return ClaimResult("in_progress", record)

    async def create_batch(self, batch_id: str, total_orders: int, summary: str) -> None:
        await asyncio.to_thread(self._create_batch, batch_id, total_orders, summary)

    def _create_batch(self, batch_id: str, total_orders: int, summary: str) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    _INSERT_BATCH,
                    {"batch_id": batch_id, "total_orders": total_orders, "summary": summary},
                )
        except Exception as exc:
            logger.exception("failed to create batch_id=%s", batch_id)
            raise OrderPersistenceError(f"Batch {batch_id} could not be saved") from exc

    async def update_batch(self, batch_id: str, status: str, summary: str) -> None:
        await asyncio.to_thread(self._update_batch, batch_id, status, summary)

    def _update_batch(self, batch_id: str, status: str, summary: str) -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    _UPDATE_BATCH,
                    {"batch_id": batch_id, "status": status, "summary": summary},
                )
        except Exception as exc:
            logger.exception("failed to update batch_id=%s", batch_id)
            raise OrderPersistenceError(f"Batch {batch_id} could not be saved") from exc

    async def get_batch(self, batch_id: str) -> BatchRecord | None:
        return await asyncio.to_thread(self._get_batch, batch_id)

    def _get_batch(self, batch_id: str) -> BatchRecord | None:
        with self._engine.connect() as connection:
            row = connection.execute(_SELECT_BATCH, {"batch_id": batch_id}).mappings().first()
        if row is None:
            return None
        return BatchRecord(
            batch_id=row["batch_id"],
            total_orders=row["total_orders"],
            status=row["status"],
            summary=row["summary"] or "",
        )


def _record(row: Any) -> OrderRecord:
    return OrderRecord(
        id=row["id"],
        order_id=row["order_id"],
        courier_partner=row["courier_partner"],
        status=row["status"],
        raw_request_payload=row["raw_request_payload"] or "",
        raw_response_payload=row["raw_response_payload"] or "",
        courier_order_id=row["courier_order_id"],
        awb_number=row["awb_number"],
    )


def _classify_existing(record: OrderRecord | None) -> ClaimResult:
    if record is None or record.status == "PROCESSING":
        return ClaimResult("in_progress", record)
    if record.status == "CANCELLED":
        return ClaimResult("cancelled", record)
    return ClaimResult("exists", record)


_CLAIM = text(
    """
    INSERT INTO orders (
        id,
        order_id,
        courier_partner,
        status,
        raw_request_payload,
        raw_response_payload
    ) VALUES (
        :id,
        :order_id,
        :courier_partner,
        'PROCESSING',
        :raw_request_payload,
        ''
    )
    """
)

_RECLAIM_FAILED = text(
    """
    UPDATE orders
    SET courier_partner = :courier_partner,
        status = 'PROCESSING',
        raw_request_payload = :raw_request_payload,
        raw_response_payload = '',
        updated_at = CURRENT_TIMESTAMP
    WHERE order_id = :order_id
      AND status = 'FAILED'
      AND awb_number IS NULL
    """
)

_SELECT_BY_ORDER = text(
    """
    SELECT
        id,
        order_id,
        courier_partner,
        courier_order_id,
        awb_number,
        status,
        raw_request_payload,
        raw_response_payload
    FROM orders
    WHERE order_id = :order_id
    """
)

_INSERT_BATCH = text(
    """
    INSERT INTO bulk_batches (batch_id, total_orders, status, summary)
    VALUES (:batch_id, :total_orders, 'PROCESSING', :summary)
    """
)

_UPDATE_BATCH = text(
    """
    UPDATE bulk_batches
    SET status = :status,
        summary = :summary,
        updated_at = CURRENT_TIMESTAMP
    WHERE batch_id = :batch_id
    """
)

_SELECT_BATCH = text(
    """
    SELECT batch_id, total_orders, status, summary
    FROM bulk_batches
    WHERE batch_id = :batch_id
    """
)
