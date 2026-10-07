from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

import httpx

from sentinelward.contracts import AgentEventEnvelope
from sentinelward.errors import DeliveryError


@dataclass(frozen=True, slots=True)
class BackendEventClient:
    base_url: str
    token: str
    timeout_seconds: float = 5.0
    max_attempts: int = 3
    transport: httpx.AsyncBaseTransport | None = None

    async def health(self) -> bool:
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, transport=self.transport
            ) as client:
                response = await client.get(
                    f"{self.base_url.rstrip('/')}/health/live", headers=headers
                )
                return 200 <= response.status_code < 300
        except (httpx.TimeoutException, httpx.NetworkError):
            return False

    async def publish(self, event: AgentEventEnvelope) -> str:
        url = f"{self.base_url.rstrip('/')}/internal/v1/agent-events"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Idempotency-Key": event.event_id,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, transport=self.transport
        ) as client:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await client.post(
                        url, headers=headers, json=event.model_dump(mode="json")
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == self.max_attempts:
                        raise DeliveryError(
                            "BACKEND_UNAVAILABLE", str(exc), retryable=True
                        ) from exc
                    await asyncio.sleep(_retry_delay(attempt))
                    continue

                if 200 <= response.status_code < 300:
                    return str(response.headers.get("X-Event-Id", event.event_id))
                if response.status_code in {401, 403}:
                    raise DeliveryError(
                        "BACKEND_AUTH_FAILED", "backend rejected service identity", retryable=False
                    )
                if response.status_code in {400, 404, 409, 422}:
                    raise DeliveryError(
                        "BACKEND_REJECTED",
                        _safe_response_detail(response),
                        retryable=False,
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.max_attempts:
                        await asyncio.sleep(_retry_delay(attempt))
                        continue
                    raise DeliveryError(
                        "BACKEND_TRANSIENT_FAILURE",
                        f"backend returned HTTP {response.status_code}",
                        retryable=True,
                    )
                raise DeliveryError(
                    "BACKEND_HTTP_ERROR",
                    f"backend returned HTTP {response.status_code}",
                    retryable=False,
                )
        raise AssertionError("retry loop exited unexpectedly")


def _retry_delay(attempt: int) -> float:
    return float(min(2.0, 0.2 * (2 ** (attempt - 1))) + random.uniform(0, 0.05))


def _safe_response_detail(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        try:
            data = response.json()
            if isinstance(data, dict) and isinstance(data.get("detail"), str):
                return str(data["detail"])[:240]
        except ValueError:
            pass
    return f"backend returned HTTP {response.status_code}"
