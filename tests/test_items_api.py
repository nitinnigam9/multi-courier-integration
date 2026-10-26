"""API tests."""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.application.use_cases.items import CreateItem
from app.domain.exceptions import InvalidItem
from app.infrastructure.config import Settings
from app.infrastructure.persistence.memory_item_repository import MemoryItemRepository
from app.infrastructure.system_clock import SystemClock
from app.interfaces.api.app import create_app
from app.interfaces.api.middleware import client_partition


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "burst_quota": 10,
        "burst_window_seconds": 60,
        "sustained_quota": 50,
        "sustained_window_seconds": 3600,
        "trust_proxy": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(_settings())) as test_client:
        yield test_client


def test_create_list_and_get_item(client: TestClient) -> None:
    created = client.post("/api/v1/items", json={"name": "  notebook  "})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "notebook"
    assert created.headers["ratelimit-policy"].startswith('"burst";q=10;w=60;qu="requests"')
    assert '"burst";r=9;t=60' in created.headers["ratelimit"]

    listed = client.get("/api/v1/items")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]

    fetched = client.get(f"/api/v1/items/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "notebook"


def test_missing_item_is_a_problem(client: TestClient) -> None:
    response = client.get("/api/v1/items/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Item not found"


def test_blank_name_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/items", json={"name": "   "})
    assert response.status_code == 422
    assert response.json()["title"] == "Unprocessable Entity"


def test_quota_exceeded_uses_standard_headers() -> None:
    with TestClient(create_app(_settings(burst_quota=2, sustained_quota=5))) as client:
        headers = {"x-api-key": "tenant-a"}
        assert client.get("/api/v1/items", headers=headers).status_code == 200
        assert client.get("/api/v1/items", headers=headers).status_code == 200

        blocked = client.get("/api/v1/items", headers=headers)
        assert blocked.status_code == 429
        assert blocked.headers["content-type"].startswith("application/problem+json")
        body = blocked.json()
        assert body["type"].endswith("#quota-exceeded")
        assert body["violated-policies"] == ["burst"]
        assert body["status"] == 429
        assert blocked.headers["ratelimit-policy"].startswith('"burst";q=2;w=60;qu="requests"')
        assert '"burst";r=0;t=' in blocked.headers["ratelimit"]
        assert int(blocked.headers["retry-after"]) == 60

        other_tenant = client.get("/api/v1/items", headers={"x-api-key": "tenant-b"})
        assert other_tenant.status_code == 200


def test_health_is_exempt(client: TestClient) -> None:
    for _ in range(5):
        response = client.get("/health")
        assert response.status_code == 200
        assert "ratelimit" not in response.headers


def test_forwarded_for_is_ignored_unless_proxy_is_trusted() -> None:
    with TestClient(create_app(_settings(burst_quota=1))) as client:
        first = client.get("/api/v1/items", headers={"x-forwarded-for": "203.0.113.5"})
        second = client.get("/api/v1/items", headers={"x-forwarded-for": "203.0.113.9"})
    assert first.status_code == 200
    assert second.status_code == 429

    with TestClient(create_app(_settings(burst_quota=1, trust_proxy=True))) as client:
        first = client.get("/api/v1/items", headers={"x-forwarded-for": "203.0.113.5"})
        second = client.get("/api/v1/items", headers={"x-forwarded-for": "203.0.113.9"})
    assert first.status_code == 200
    assert second.status_code == 200


def test_use_case_rejects_a_blank_name() -> None:
    use_case = CreateItem(MemoryItemRepository(), SystemClock())
    with pytest.raises(InvalidItem):
        asyncio.run(use_case.execute("   "))


def test_partition_uses_api_key_before_address() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"x-api-key", b"secret"), (b"x-forwarded-for", b"203.0.113.5")],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
    }
    partition = client_partition(Request(scope), trust_proxy=True)
    assert partition.startswith("key:")
    assert "secret" not in partition
