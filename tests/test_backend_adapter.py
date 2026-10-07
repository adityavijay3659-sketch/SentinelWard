from __future__ import annotations

import httpx
import pytest

from sentinelward.adapters.backend import BackendEventClient
from sentinelward.contracts import AgentEventEnvelope
from sentinelward.errors import DeliveryError


def event() -> AgentEventEnvelope:
    return AgentEventEnvelope(
        v=1,
        event_id="evt_000231",
        event_type="ticket.updated",
        ts=1_792_252_801_200,
        source_agent="A6",
        bed_id="B05",
        device_id="MON-05",
        correlation_id="B05:1792252795000:DRIFTING",
        payload={"status": "open"},
    )


@pytest.mark.asyncio
async def test_backend_success_sends_identity_and_idempotency_headers() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["idempotency-key"] == "evt_000231"
        return httpx.Response(202, headers={"X-Event-Id": "evt_000231"})

    client = BackendEventClient(
        "https://backend.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    assert await client.publish(event()) == "evt_000231"


@pytest.mark.asyncio
async def test_backend_auth_failure_is_not_retryable() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401)

    client = BackendEventClient(
        "https://backend.test",
        "bad",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(DeliveryError) as captured:
        await client.publish(event())
    assert captured.value.code == "BACKEND_AUTH_FAILED"
    assert captured.value.retryable is False
    assert attempts == 1


@pytest.mark.asyncio
async def test_backend_health_is_false_on_network_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    client = BackendEventClient(
        "https://backend.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    assert await client.health() is False
