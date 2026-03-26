"""Integration tests for /api/v1/items endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_health_check(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_create_item(client: AsyncClient):
    response = await client.post("/api/v1/items/", json={"title": "Test item"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test item"
    assert data["is_active"] is True
    assert "id" in data


async def test_list_items_empty(client: AsyncClient):
    response = await client.get("/api/v1/items/")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_items(client: AsyncClient):
    await client.post("/api/v1/items/", json={"title": "Item A"})
    await client.post("/api/v1/items/", json={"title": "Item B"})
    response = await client.get("/api/v1/items/")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_item(client: AsyncClient):
    create_resp = await client.post("/api/v1/items/", json={"title": "Get me"})
    item_id = create_resp.json()["id"]
    response = await client.get(f"/api/v1/items/{item_id}")
    assert response.status_code == 200
    assert response.json()["id"] == item_id


async def test_get_item_not_found(client: AsyncClient):
    response = await client.get("/api/v1/items/9999")
    assert response.status_code == 404


async def test_update_item(client: AsyncClient):
    create_resp = await client.post("/api/v1/items/", json={"title": "Original"})
    item_id = create_resp.json()["id"]
    response = await client.patch(
        f"/api/v1/items/{item_id}", json={"title": "Updated"}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Updated"


async def test_delete_item(client: AsyncClient):
    create_resp = await client.post("/api/v1/items/", json={"title": "Delete me"})
    item_id = create_resp.json()["id"]
    del_resp = await client.delete(f"/api/v1/items/{item_id}")
    assert del_resp.status_code == 204
    get_resp = await client.get(f"/api/v1/items/{item_id}")
    assert get_resp.status_code == 404
