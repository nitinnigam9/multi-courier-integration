# Assignment API

FastAPI service for booking, tracking, and cancelling Urbanebolt shipments, including a bulk create that returns immediately and finishes in the background.

## Run locally

Requirements: Python 3.11 or newer, and MySQL 8 running on `127.0.0.1:3306`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Create the empty database, then edit `.env`:

1. Set `DATABASE_URL` to your MySQL user, password, host, and database. Use `127.0.0.1`, not `localhost`, so the client does not look for a local socket.
2. Set `courier_username`, `courier_password`, `courier_customer_code`, and `courier_csrf_token`. The CSRF value is sent as `Cookie: csrftoken=...` on courier login only.

Apply the schema in [Database schema](#database-schema), then start the API:

```bash
uvicorn app.main:app --reload
```

- API base: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs

`--reload` picks up code and `.env` changes. Restart the process if it was started without `--reload`.

Send `X-API-Key` to give a caller its own rate-limit bucket. Without that header, the limit is per client address. `/health`, `/docs`, `/redoc`, and `/openapi.json` are not limited.

## Endpoints

### `GET /health`

Liveness check. No courier call and no database call.

```bash
curl -s http://127.0.0.1:8000/health
```

```json
{"status": "ok"}
```

### `POST /api/v1/orders`

Books one shipment. The API logs in to Urbanebolt, maps this body onto a manifest, and posts it to `/api/v1/services/manifest/`. A successful booking is stored in `orders` with status `MANIFESTED` and returns `201`. A courier rejection is stored as `FAILED` and returned with the courier status and message.

`order_id` is unique. Sending the same `order_id` again updates that row; the bulk endpoint is the one that refuses a second shipment.

`payment_mode` is `PREPAID` or `COD`. `PREPAID` is sent to the courier as `PPD` with `collectableValue` 0. `COD` is sent as `COD` with `collectableValue` equal to `declared_value`.

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/orders \
  -H 'content-type: application/json' \
  -H 'x-api-key: demo' \
  -d @- <<'EOF'
{
  "order_id": "ORD-2026-1026A",
  "courier_partner": "urbanebolt",
  "pickup_details": {
    "contact_name": "Warehouse Alpha",
    "phone": "+919876543210",
    "email": "warehouse@ecommerce.com",
    "address_line1": "Plot No. 42, Phase 3, Industrial Area",
    "address_line2": "Near Main Highway",
    "city": "Indore",
    "state": "Madhya Pradesh",
    "pincode": "452001",
    "country": "India"
  },
  "delivery_details": {
    "contact_name": "Rahul Sharma",
    "phone": "+919123456789",
    "email": "rahul.sharma@email.com",
    "address_line1": "Flat 304, Royal Apartments",
    "address_line2": "Vijay Nagar",
    "city": "Indore",
    "state": "Madhya Pradesh",
    "pincode": "452010",
    "country": "India"
  },
  "package_details": {
    "weight_kg": 1.25,
    "dimensions": {"length_cm": 20.0, "width_cm": 15.0, "height_cm": 10.0},
    "payment_mode": "PREPAID",
    "declared_value": 2499.00,
    "currency": "INR"
  },
  "items": [
    {"sku": "SKU-PROD-XYZ123", "name": "Wireless Ergonomic Mouse", "quantity": 1, "price": 2499.00}
  ]
}
EOF
```

`201` body: `order_id`, `courier_partner`, and `manifest` (the courier JSON). Only `courier_partner` `urbanebolt` is supported; any other value is `422`.

### `POST /api/v1/orders/bulk`

Books up to 100 orders. The body is a JSON array of the same objects as `POST /api/v1/orders`.

The call inserts a `bulk_batches` row and returns `202` with a `batch_id` before any manifest call. Manifests then run in this process, up to `BULK_CONCURRENCY` (default 10) at a time. They are not sent one after another inside the HTTP request.

`order_id` is idempotent:

- An `order_id` that already has a shipment is not sent again. The result is `succeeded` with reason `Order already submitted`.
- An `order_id` that previously failed, and has no airway bill, is sent again.
- A cancelled `order_id` is not sent again.
- A duplicate `order_id` inside the same array fails that extra row only.

A courier or partner failure fails that order only. The batch finishes as `COMPLETED` when every order succeeded, or `COMPLETED_WITH_ERRORS` when any failed. Poll until `pending` is 0.

If the API process stops mid-batch, the row can stay `PROCESSING` and is not resumed.

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/orders/bulk \
  -H 'content-type: application/json' \
  -H 'x-api-key: demo' \
  -d @orders.json
```

`202` body:

```json
{
  "batch_id": "4f1c0c2e-7b2a-4d1e-9c3a-6b8e1d0a9f22",
  "status": "PROCESSING",
  "total_orders": 2,
  "succeeded": 0,
  "failed": 0,
  "pending": 2,
  "results": []
}
```

### `GET /api/v1/orders/bulk/{batch_id}`

Reads the batch written by the bulk create. `results` lists finished orders. Each item has `order_id`, `courier_partner`, `status` (`succeeded` or `failed`), `reason`, and `awb_number`. Unknown `batch_id` is `404`.

```bash
curl -s http://127.0.0.1:8000/api/v1/orders/bulk/4f1c0c2e-7b2a-4d1e-9c3a-6b8e1d0a9f22 \
  -H 'x-api-key: demo'
```

### `GET /api/v1/orders/{order_id}/track`

Loads the stored order for `order_id` and `courier_partner`, then calls Urbanebolt tracking with the stored airway bill. The latest status is written to `orders.status` and appended to `tracking_history`.

`courier_partner` is a required query parameter. Missing order is `404`. An order with no airway bill is `422`.

```bash
curl -s 'http://127.0.0.1:8000/api/v1/orders/ORD-2026-1026A/track?courier_partner=urbanebolt' \
  -H 'x-api-key: demo'
```

`200` body: `order_id`, `awb_number`, `courier_partner`, and `tracking` (the courier JSON).

### `POST /api/v1/orders/{order_id}/cancel`

Loads the stored order and posts `{"awbs": "<awb>"}` to the Urbanebolt cancel API. On success the order status becomes `CANCELLED`.

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/orders/ORD-2026-1026A/cancel \
  -H 'content-type: application/json' \
  -H 'x-api-key: demo' \
  -d '{"courier_partner": "urbanebolt"}'
```

`200` body: `order_id`, `awb_number`, `courier_partner`, and `cancellation` (the courier JSON). Missing order is `404`. An order with no airway bill is `422`.

## Database schema

Empty schema for database `multi_courier_system`. No seed rows.

```sql
CREATE DATABASE IF NOT EXISTS multi_courier_system
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE multi_courier_system;

CREATE TABLE orders (
  id varchar(36) NOT NULL,
  order_id varchar(100) NOT NULL,
  courier_partner varchar(50) NOT NULL,
  courier_order_id varchar(100) DEFAULT NULL,
  awb_number varchar(100) DEFAULT NULL,
  status varchar(50) NOT NULL,
  raw_request_payload text,
  raw_response_payload text,
  created_at timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY order_id (order_id),
  KEY idx_orders_order_id (order_id),
  KEY idx_orders_awb_number (awb_number)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE tracking_history (
  id varchar(36) NOT NULL,
  order_id varchar(100) NOT NULL,
  status varchar(50) NOT NULL,
  raw_status_payload text,
  recorded_at timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_tracking_order_id (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE bulk_batches (
  batch_id varchar(36) NOT NULL,
  total_orders int NOT NULL,
  status varchar(50) NOT NULL,
  summary text,
  created_at timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (batch_id),
  KEY idx_bulk_batches_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

`orders.order_id` is the idempotency key. `tracking_history` is one row per track or cancel snapshot. `bulk_batches.summary` is the JSON polled by `GET /api/v1/orders/bulk/{batch_id}`.

## Configuration

| Variable | Meaning | Default |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy MySQL URL | empty |
| `courier_partner` | Partner name this process books | `urbanebolt` |
| `courier_partner_url` | Urbanebolt origin | empty |
| `courier_username` / `courier_password` | Login for `getToken` | empty |
| `courier_csrf_token` | `csrftoken` cookie sent on login | empty |
| `courier_customer_code` | Manifest `customerCode` | empty |
| `courier_service_type` | Manifest `serviceType` | `SDD` |
| `BULK_CONCURRENCY` | Manifest calls in flight for one bulk batch | `10` |
| `APP_BURST_QUOTA` | Requests allowed in the short window | `30` |
| `APP_BURST_WINDOW_SECONDS` | Short window length | `60` |
| `APP_SUSTAINED_QUOTA` | Requests allowed in the long window | `1000` |
| `APP_SUSTAINED_WINDOW_SECONDS` | Long window length | `3600` |
| `APP_RATE_LIMIT_ENABLED` | Turn the middleware off | `true` |
| `APP_TRUST_PROXY` | Honor `X-Forwarded-For` for the client address | `false` |

Rate limits follow the IETF rate-limit header fields. Both `burst` and `sustained` must have quota. A rejected request is not counted and returns `429` with `Retry-After` and `application/problem+json`.

## Layout

Dependencies point inward. Routers do not import the repository implementation, and the domain does not import FastAPI.

```text
app/
  domain/            entities, exceptions, repository and clock ports
  application/       use cases and the rate-limiter port
  infrastructure/    settings, MySQL, courier client, sliding-window limiter
  interfaces/api/    FastAPI routes, schemas, middleware, error mapping
  main.py            process entrypoint
```
