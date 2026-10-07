from __future__ import annotations

import httpx
import pytest

from sentinelward.api import create_app
from sentinelward.health import HealthRegistry


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
