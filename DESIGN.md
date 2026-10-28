# Design

## Architecture

The service is a FastAPI process organised as clean architecture. Dependencies point inward. The domain does not import FastAPI, SQLAlchemy, or HTTP. Use cases depend on ports. Adapters sit at the edge and are wired once in `create_app`.

```text
interfaces/api   routes, schemas, rate-limit middleware, problem+json errors
application      CreateOrder, TrackOrder, CancelOrder, SubmitBulkOrders
domain           Order, exceptions, OrderRepository and Clock ports
infrastructure   Urbanebolt HTTP client, MySQL repository, in-memory limiter
```

A request passes the rate-limit middleware, then a router. The router maps JSON to an `Order` and calls a use case. The use case calls `CourierGateway` and `OrderRepository`. `UrbaneboltCourier` logs in with `POST /api/v1/auth/getToken/` (CSRF cookie on that call only) and sends later calls with `Authorization: Bearer`. `MysqlOrderRepository` is the only writer of `orders`, `tracking_history`, and `bulk_batches`.

Single create waits for the courier and returns `201`. Bulk create inserts a batch row and returns `202` with a `batch_id`. A background task then manifests orders with a bounded number of calls in flight. Clients poll `GET /api/v1/orders/bulk/{batch_id}`.

## Pattern and why

The structural pattern is ports and adapters (hexagonal architecture).

`CourierGateway` and `OrderRepository` are the ports. `UrbaneboltCourier` and `MysqlOrderRepository` are the adapters. Use cases such as `CreateOrder` and `SubmitBulkOrders` contain the booking rules and receive those ports in their constructors. `create_app` is the composition root: it builds the adapters and stores the use cases on `app.state`.

This split is used so the booking rules stay testable without a live courier or a database, and so a second courier or a different database can be added by writing an adapter rather than editing the use case. The domain stays free of framework types, so a change in FastAPI or SQLAlchemy does not ripple into the order model.

Two smaller patterns sit on the same idea. The rate limiter is a port (`RateLimiter`) with an in-memory sliding-window adapter, applied as middleware so every route shares one policy. Bulk processing is a claim-then-act flow: an `order_id` is reserved in MySQL before the manifest call, which is what makes a second submit unable to create a second shipment.

## Database schema

Database `multi_courier_system`. The executable DDL is in `README.md`. There is no seed data.

**orders.** One row per `order_id`. `id` is the primary key. `order_id` is unique and is the idempotency key. Other columns: `courier_partner`, `courier_order_id`, `awb_number`, `status` (`PROCESSING`, `MANIFESTED`, `FAILED`, `CANCELLED`, or a tracking status), `raw_request_payload`, `raw_response_payload`, `created_at`, `updated_at`. Indexes on `order_id` and `awb_number`.

**tracking_history.** One row per track or cancel snapshot. Columns: `id`, `order_id`, `status`, `raw_status_payload`, `recorded_at`. Indexed by `order_id`. Tracking also updates `orders.status`. Cancel sets that status to `CANCELLED` and does not overwrite `raw_response_payload`.

**bulk_batches.** One row per bulk request. `batch_id` is the primary key. Columns: `total_orders`, `status` (`PROCESSING`, `COMPLETED`, `COMPLETED_WITH_ERRORS`), `summary` (JSON with `succeeded`, `failed`, `pending`, and per-order `results`), `created_at`, `updated_at`.

`orders` is written by single create, bulk, track, and cancel. `bulk_batches` is written only by the bulk flow. The summary is rewritten as each order finishes, so a poll during the run already shows partial results.

## Trade-offs

**202 and poll, not a stream or a blocking call.** The bulk handler returns before the courier work. A proxy timeout cannot abandon the batch, and 100 manifests do not occupy one HTTP request. The cost is that the client must poll, and the `202` body is not the final result. A stream would deliver results on one connection but would stay open for the slowest order. Waiting for every manifest would make partial progress invisible until the end and would risk gateway timeouts.

**In-process background work.** `asyncio` runs the batch inside the API process, with a semaphore (default 10) so calls overlap without a stampede. No worker or broker is required. A process restart leaves the batch in `PROCESSING` and does not resume it. Orders already claimed as `PROCESSING` are not sent again until that state is cleared. A durable queue would survive restarts and would be the next step if more than one API process books orders.

**One manifest HTTP call per order.** Each order is posted on its own so a rejection stays attached to that `order_id`. Urbanebolt also accepts an array, which would be fewer calls, but one error for the array is harder to split into the 95-success / 5-failure response this API has to return. Calls for one batch still run concurrently.

**Idempotency in the orders table.** The unique `order_id` is reserved before the courier call. An existing shipment is returned as `Order already submitted` and is not manifested again. A previous `FAILED` row with no airway bill can be retried. The same check covers single-create rows and bulk rows. Two requests racing on a new `order_id` produce one insert; the loser sees the row in progress and does not book a second shipment.

**Courier payloads stored as text.** Request and response JSON are kept on the order row so a failure can be explained without another service. Line items are not normalised. That keeps the schema small and matches a courier whose contract is a document. It makes item-level queries and large batches (the summary is a `TEXT` column, and the API caps a batch at 100 orders) a poor fit.

**Rate limit in memory.** Burst and sustained windows are counted in the process, partitioned by hashed `X-API-Key` or client address. Rejected requests do not consume quota. The counters are not shared across processes and reset on restart. A Redis adapter can implement the same port when several instances serve traffic.

**One courier adapter.** Anything other than the configured partner fails that order only. The port is ready for another adapter; partner-specific mapping stays inside `UrbaneboltCourier`, not in the use case.
