# Assignment API

FastAPI service laid out as clean architecture, with HTTP rate limiting that follows the IETF rate-limit header fields (`RateLimit-Policy`, `RateLimit`), `429 Too Many Requests`, `Retry-After`, and `application/problem+json`.

## Layout

Dependencies point inward. Routers never import the repository implementation, and the domain never imports FastAPI.

```text
app/
  domain/            entities, exceptions, repository and clock ports
  application/       use cases and the rate-limiter port
  infrastructure/    settings, in-memory storage, sliding-window limiter
  interfaces/api/    FastAPI routes, schemas, middleware, error mapping
  main.py            process entrypoint
```

`create_app` is the composition root. It wires the in-memory repository and the limiter, then hands use cases to the routers through `app.state`. Replace `MemoryItemRepository` or `SlidingWindowRateLimiter` without changing a route.

## Rate limiting

Two policies are enforced together. A request is allowed only when both still have quota. A rejected request is not counted.

| Policy | Default quota | Window |
| --- | --- | --- |
| `burst` | 30 requests | 60 seconds |
| `sustained` | 1000 requests | 3600 seconds |

Quota is partitioned by `X-API-Key` when that header is present, otherwise by client address. The partition key is hashed before it is stored. `X-Forwarded-For` is ignored unless `APP_TRUST_PROXY=true`.

`/health`, `/docs`, `/redoc`, and `/openapi.json` are not limited.

Allowed response:

```http
RateLimit-Policy: "burst";q=30;w=60;qu="requests","sustained";q=1000;w=3600;qu="requests"
RateLimit: "burst";r=29;t=60,"sustained";r=999;t=3600
```

Exhausted response:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/problem+json
Retry-After: 12
RateLimit: "burst";r=0;t=12,"sustained";r=970;t=3400

{
  "type": "https://iana.org/assignments/http-problem-types#quota-exceeded",
  "title": "Request cannot be satisfied as assigned quota has been exceeded",
  "status": 429,
  "violated-policies": ["burst"]
}
```

The window is a sliding window. `t` is the number of seconds until the oldest counted request leaves the window, which is the effective window from the header draft. The algorithm is an adapter detail; the header contract is the standard.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

Interactive docs: http://127.0.0.1:8000/docs

```bash
curl -i http://127.0.0.1:8000/api/v1/items \
  -H 'content-type: application/json' \
  -H 'x-api-key: demo' \
  -d '{"name":"notebook"}'
```

## Test

```bash
pytest
```

## Configuration

| Variable | Meaning | Default |
| --- | --- | --- |
| `APP_BURST_QUOTA` | Requests allowed in the short window | `30` |
| `APP_BURST_WINDOW_SECONDS` | Short window length | `60` |
| `APP_SUSTAINED_QUOTA` | Requests allowed in the long window | `1000` |
| `APP_SUSTAINED_WINDOW_SECONDS` | Long window length | `3600` |
| `APP_RATE_LIMIT_ENABLED` | Turn the middleware off | `true` |
| `APP_TRUST_PROXY` | Honor `X-Forwarded-For` for the client address | `false` |
