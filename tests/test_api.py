from __future__ import annotations

import httpx
import pytest

from sentinelward.alerts import AlertRecord
from sentinelward.api import create_app
from sentinelward.contracts import Verdict
from sentinelward.health import HealthRegistry


class FakeAlerts:
    async def acknowledge(
        self, alert_id: str, *, by: str, at_ms: int, event_id: str
    ) -> AlertRecord:
        del at_ms, event_id
        return _alert(alert_id, "acknowledged", by)

    async def escalate(self, alert_id: str, *, by: str, at_ms: int, event_id: str) -> AlertRecord:
        del by, at_ms, event_id
        return _alert(alert_id, "escalated", None)


def _alert(alert_id: str, status: str, acked_by: str | None) -> AlertRecord:
    return AlertRecord(
        alert_id=alert_id,
        bed_id="B02",
        verdict=Verdict.EMERGENCY,
        priority="high",
        text="Bed 2 — possible heart emergency. Go now.",
        recipients=["staff:priya"],
        ladder_step=1,
        status=status,
        created_ts=1_000,
        updated_ts=2_000,
        source_window_start=500,
        acked_by=acked_by,
        acked_ts=2_000 if acked_by else None,
        response_ms=1_000 if acked_by else None,
    )


@pytest.mark.asyncio
async def test_readiness_reports_each_dependency() -> None:
    health = HealthRegistry()
    transport = httpx.ASGITransport(app=create_app(health))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health/live")).status_code == 200
        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"] == {
            "postgres": False,
            "mqtt": False,
            "backend": False,
        }
        for dependency in health.dependencies:
            health.set(dependency, True)
        assert (await client.get("/health/ready")).status_code == 200
        metrics = await client.get("/metrics")
        assert metrics.status_code == 200
        assert 'dependency="mqtt"} 1' in metrics.text


@pytest.mark.asyncio
async def test_internal_alert_commands_require_auth_and_return_one_line() -> None:
    app = create_app(HealthRegistry(), alerts=FakeAlerts(), service_token="secret")
    transport = httpx.ASGITransport(app=app)
    command = {
        "v": 1,
        "event_id": "screen-1",
        "ts": 2_000,
        "by": "staff:priya",
        "source": "screen",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.post("/internal/v1/alerts/al_1/ack", json=command)).status_code == 401
        response = await client.post(
            "/internal/v1/alerts/al_1/ack",
            json=command,
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["alert"]["acked_by"] == "staff:priya"
    assert "\n" not in payload["summary"]
    assert len(payload["summary"]) <= 160
    assert payload["outputs"]["team"] == payload["summary"]
    assert "staff:" not in payload["outputs"]["user"]
    assert payload["outputs"]["model"] == payload["alert"]
