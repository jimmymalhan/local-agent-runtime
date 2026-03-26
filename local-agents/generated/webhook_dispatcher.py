"""Webhook Dispatcher Service — FastAPI + asyncio with retry/backoff."""

import asyncio
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="Webhook Dispatcher")

# --- Storage ---
webhooks: Dict[str, dict] = {}
event_log: List[dict] = []
delivery_log: List[dict] = []

# --- Config ---
MAX_RETRIES = 3
BACKOFF_BASE = 1  # seconds


# --- Models ---
class WebhookRegister(BaseModel):
    url: HttpUrl
    secret: Optional[str] = None
    events: Optional[List[str]] = None  # filter by event type; None = all


class EventPayload(BaseModel):
    type: str
    data: Dict[str, Any]


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: Optional[List[str]]
    created_at: str


class EventResponse(BaseModel):
    event_id: str
    type: str
    dispatched_to: int
    timestamp: str


# --- Helpers ---
async def dispatch_to_webhook(
    webhook_id: str, webhook: dict, event_id: str, event_type: str, payload: dict
) -> dict:
    """Deliver a single event to a single webhook with retry + exponential backoff."""
    url = str(webhook["url"])
    result = {
        "webhook_id": webhook_id,
        "event_id": event_id,
        "url": url,
        "attempts": 0,
        "status": "pending",
        "status_code": None,
        "error": None,
    }

    for attempt in range(MAX_RETRIES + 1):
        result["attempts"] = attempt + 1
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    json={"event_id": event_id, "type": event_type, "data": payload},
                    headers={"X-Webhook-Secret": webhook.get("secret") or ""},
                )
            result["status_code"] = resp.status_code
            if resp.status_code < 400:
                result["status"] = "delivered"
                break
            # 4xx → don't retry (client error on receiver side)
            if 400 <= resp.status_code < 500:
                result["status"] = "failed"
                result["error"] = f"Client error: {resp.status_code}"
                break
            # 5xx → retry
            result["error"] = f"Server error: {resp.status_code}"
        except httpx.RequestError as exc:
            result["error"] = str(exc)

        if attempt < MAX_RETRIES:
            await asyncio.sleep(BACKOFF_BASE * (2**attempt))

    if result["status"] == "pending":
        result["status"] = "failed"

    delivery_log.append(result)
    return result


async def fan_out(event_id: str, event_type: str, payload: dict) -> List[dict]:
    """Dispatch an event to every matching registered webhook in parallel."""
    tasks = []
    for wh_id, wh in webhooks.items():
        # If webhook filters by event type, skip non-matching
        if wh.get("events") and event_type not in wh["events"]:
            continue
        tasks.append(dispatch_to_webhook(wh_id, wh, event_id, event_type, payload))
    if not tasks:
        return []
    return await asyncio.gather(*tasks)


# --- Routes ---
@app.post("/webhooks", response_model=WebhookResponse, status_code=201)
async def register_webhook(body: WebhookRegister):
    wh_id = str(uuid.uuid4())
    record = {
        "id": wh_id,
        "url": str(body.url),
        "secret": body.secret,
        "events": body.events,
        "created_at": datetime.utcnow().isoformat(),
    }
    webhooks[wh_id] = record
    return WebhookResponse(
        id=wh_id, url=record["url"], events=record["events"], created_at=record["created_at"]
    )


@app.get("/webhooks")
async def list_webhooks():
    return [
        {"id": w["id"], "url": w["url"], "events": w["events"], "created_at": w["created_at"]}
        for w in webhooks.values()
    ]


@app.delete("/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str):
    if webhook_id not in webhooks:
        raise HTTPException(status_code=404, detail="Webhook not found")
    del webhooks[webhook_id]


@app.post("/events", response_model=EventResponse, status_code=202)
async def receive_event(body: EventPayload):
    event_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()
    event_log.append(
        {"event_id": event_id, "type": body.type, "data": body.data, "timestamp": timestamp}
    )
    # Fan out in background so the caller doesn't wait
    matching = [
        wh_id
        for wh_id, wh in webhooks.items()
        if not wh.get("events") or body.type in wh["events"]
    ]
    asyncio.create_task(fan_out(event_id, body.type, body.data))
    return EventResponse(
        event_id=event_id, type=body.type, dispatched_to=len(matching), timestamp=timestamp
    )


@app.get("/deliveries")
async def list_deliveries():
    return delivery_log


# --- Self-test ---
if __name__ == "__main__":
    import json as _json
    from unittest.mock import AsyncMock, patch

    # Helper to run async tests
    def run(coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    # -- Unit tests for dispatch logic with mocked HTTP --

    # Reset state
    webhooks.clear()
    event_log.clear()
    delivery_log.clear()

    # Patch BACKOFF_BASE to 0 for fast tests
    _orig_backoff = BACKOFF_BASE

    async def run_tests():
        global BACKOFF_BASE
        BACKOFF_BASE = 0  # no wait during tests

        # --- Test 1: Successful delivery ---
        mock_response_ok = httpx.Response(200, json={"ok": True})
        wh_id = "wh-success"
        wh = {"url": "https://example.com/hook", "secret": "s3cret", "events": None}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response_ok):
            result = await dispatch_to_webhook(wh_id, wh, "evt-1", "order.created", {"id": 1})

        assert result["status"] == "delivered", f"Expected delivered, got {result['status']}"
        assert result["attempts"] == 1
        assert result["status_code"] == 200
        print("[PASS] Test 1: Successful delivery on first attempt")

        # --- Test 2: Retry on 500, then succeed ---
        call_count = 0

        async def mock_post_retry(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return httpx.Response(502)
            return httpx.Response(200, json={"ok": True})

        delivery_log.clear()
        with patch("httpx.AsyncClient.post", side_effect=mock_post_retry):
            result = await dispatch_to_webhook("wh-retry", wh, "evt-2", "order.created", {"id": 2})

        assert result["status"] == "delivered", f"Expected delivered, got {result['status']}"
        assert result["attempts"] == 3, f"Expected 3 attempts, got {result['attempts']}"
        print("[PASS] Test 2: Retried 2x on 502, succeeded on 3rd attempt")

        # --- Test 3: All retries exhausted → failed ---
        delivery_log.clear()
        mock_response_500 = httpx.Response(500)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response_500):
            result = await dispatch_to_webhook("wh-fail", wh, "evt-3", "order.created", {"id": 3})

        assert result["status"] == "failed"
        assert result["attempts"] == MAX_RETRIES + 1  # 4 total (1 initial + 3 retries)
        print(f"[PASS] Test 3: Failed after {result['attempts']} attempts (max retries exhausted)")

        # --- Test 4: 4xx errors are NOT retried ---
        delivery_log.clear()
        mock_response_404 = httpx.Response(404)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response_404):
            result = await dispatch_to_webhook("wh-4xx", wh, "evt-4", "order.created", {"id": 4})

        assert result["status"] == "failed"
        assert result["attempts"] == 1, f"4xx should not retry, got {result['attempts']} attempts"
        print("[PASS] Test 4: 4xx error not retried (1 attempt)")

        # --- Test 5: Network error triggers retry ---
        delivery_log.clear()
        net_call = 0

        async def mock_post_network(*args, **kwargs):
            nonlocal net_call
            net_call += 1
            if net_call <= 1:
                raise httpx.ConnectError("Connection refused")
            return httpx.Response(200, json={"ok": True})

        with patch("httpx.AsyncClient.post", side_effect=mock_post_network):
            result = await dispatch_to_webhook("wh-net", wh, "evt-5", "order.created", {"id": 5})

        assert result["status"] == "delivered"
        assert result["attempts"] == 2
        print("[PASS] Test 5: Network error retried, delivered on 2nd attempt")

        # --- Test 6: fan_out dispatches to matching webhooks only ---
        delivery_log.clear()
        webhooks.clear()
        webhooks["wh-a"] = {"url": "https://a.com/hook", "events": ["order.created"]}
        webhooks["wh-b"] = {"url": "https://b.com/hook", "events": ["user.signup"]}
        webhooks["wh-c"] = {"url": "https://c.com/hook", "events": None}  # matches all

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response_ok):
            results = await fan_out("evt-6", "order.created", {"id": 6})

        assert len(results) == 2, f"Expected 2 dispatches (wh-a + wh-c), got {len(results)}"
        dispatched_ids = {r["webhook_id"] for r in results}
        assert dispatched_ids == {"wh-a", "wh-c"}
        print("[PASS] Test 6: fan_out only dispatched to matching webhooks")

        # --- Test 7: fan_out with no matching webhooks ---
        delivery_log.clear()
        results = await fan_out("evt-7", "payment.failed", {"id": 7})
        # Only wh-c (events=None) matches
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response_ok):
            results = await fan_out("evt-7", "payment.failed", {"id": 7})
        assert len(results) == 1
        assert results[0]["webhook_id"] == "wh-c"
        print("[PASS] Test 7: Only catch-all webhook matched unknown event type")

        BACKOFF_BASE = _orig_backoff

    # -- API route tests with TestClient --
    from fastapi.testclient import TestClient

    webhooks.clear()
    event_log.clear()
    delivery_log.clear()

    tc = TestClient(app)

    # Register webhooks
    r1 = tc.post("/webhooks", json={"url": "https://httpbin.org/post", "events": ["order.created"]})
    assert r1.status_code == 201
    wh1 = r1.json()
    assert "id" in wh1
    assert wh1["url"] == "https://httpbin.org/post"
    assert wh1["events"] == ["order.created"]
    print("[PASS] Test 8: Register webhook with event filter")

    r2 = tc.post("/webhooks", json={"url": "https://httpbin.org/status/500"})
    assert r2.status_code == 201
    assert r2.json()["events"] is None
    print("[PASS] Test 9: Register catch-all webhook")

    # List webhooks
    r_list = tc.get("/webhooks")
    assert r_list.status_code == 200
    assert len(r_list.json()) == 2
    print("[PASS] Test 10: List webhooks returns 2")

    # Post event
    r_event = tc.post("/events", json={"type": "order.created", "data": {"order_id": 42}})
    assert r_event.status_code == 202
    ev = r_event.json()
    assert ev["type"] == "order.created"
    assert ev["dispatched_to"] == 2
    print("[PASS] Test 11: Post event dispatched to 2 webhooks")

    # Post event matching only catch-all
    r_event2 = tc.post("/events", json={"type": "user.signup", "data": {"user": "alice"}})
    assert r_event2.status_code == 202
    assert r_event2.json()["dispatched_to"] == 1
    print("[PASS] Test 12: Event type filter — only 1 webhook matched")

    # Delete webhook
    r_del = tc.delete(f"/webhooks/{wh1['id']}")
    assert r_del.status_code == 204
    assert len(tc.get("/webhooks").json()) == 1
    print("[PASS] Test 13: Delete webhook")

    # Delete non-existent → 404
    r_del2 = tc.delete("/webhooks/nonexistent-id")
    assert r_del2.status_code == 404
    print("[PASS] Test 14: Delete non-existent webhook → 404")

    # Validation errors
    assert tc.post("/events", json={"data": {"x": 1}}).status_code == 422
    assert tc.post("/webhooks", json={"secret": "s"}).status_code == 422
    print("[PASS] Test 15: Validation rejects incomplete payloads (422)")

    # Event log
    assert len(event_log) == 2
    assert event_log[0]["type"] == "order.created"
    print("[PASS] Test 16: Event log recorded correctly")

    # Run async dispatch tests
    run(run_tests())

    print(f"\n{'='*50}")
    print("ALL 16 TESTS PASSED")
    print(f"{'='*50}")
