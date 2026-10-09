from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

import httpx

from sentinelward.alerts import RosterSnapshot
from sentinelward.errors import DeliveryError


@dataclass(frozen=True, slots=True)
class ClinicalBackendClient:
    base_url: str
    token: str
    timeout_seconds: float = 5.0
    max_attempts: int = 3
    transport: httpx.AsyncBaseTransport | None = None

    async def get_roster(self, bed_id: str) -> RosterSnapshot:
        response = await self._get(f"/internal/v1/ward/assignments/{bed_id}")
        try:
            roster = RosterSnapshot.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise DeliveryError(
                "ROSTER_SCHEMA_INVALID", "backend returned an invalid roster", retryable=False
            ) from exc
        if roster.bed_id != bed_id:
            raise DeliveryError(
                "ROSTER_BED_MISMATCH",
                "backend roster bed does not match the requested bed",
                retryable=False,
            )
        return roster

    async def get_waveform_png(self, bed_id: str, end_ts: int) -> bytes | None:
        response = await self._get(
            f"/internal/v1/beds/{bed_id}/waveform-snapshot",
            params={"end_ts": end_ts, "seconds": 12},
        )
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if content_type != "image/png" or not response.content:
            raise DeliveryError(
                "WAVEFORM_SCHEMA_INVALID",
                "waveform endpoint did not return image/png",
                retryable=False,
            )
        return response.content

    async def _get(self, path: str, *, params: dict[str, int] | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token}"}
        url = f"{self.base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, transport=self.transport
        ) as client:
            for attempt in range(1, self.max_attempts + 1):
                try:
                    response = await client.get(url, headers=headers, params=params)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt == self.max_attempts:
                        raise DeliveryError(
                            "BACKEND_UNAVAILABLE", str(exc), retryable=True
                        ) from exc
                    await asyncio.sleep(_retry_delay(attempt))
                    continue
                if 200 <= response.status_code < 300:
                    return response
                if response.status_code in {401, 403}:
                    raise DeliveryError(
                        "BACKEND_AUTH_FAILED",
                        "backend rejected service identity",
                        retryable=False,
                    )
                if response.status_code in {400, 404, 422}:
                    raise DeliveryError(
                        "BACKEND_REJECTED",
                        f"backend returned HTTP {response.status_code}",
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
