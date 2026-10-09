from __future__ import annotations

import secrets
from typing import Annotated, Literal, Protocol

from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict

from sentinelward.alerts import AlertRecord
from sentinelward.contracts import StaffId, TimestampMs
from sentinelward.health import HealthRegistry
from sentinelward.presentation import alert_output_views, render_alert


class AlertCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    v: Literal[1]
    event_id: str
    ts: TimestampMs
    by: StaffId
    source: Literal["screen"]


class AlertCommands(Protocol):
    async def acknowledge(
        self, alert_id: str, *, by: str, at_ms: int, event_id: str
    ) -> AlertRecord: ...

    async def escalate(
        self, alert_id: str, *, by: str, at_ms: int, event_id: str
    ) -> AlertRecord: ...


def create_app(
    health: HealthRegistry,
    *,
    alerts: AlertCommands | None = None,
    service_token: str | None = None,
) -> FastAPI:
    app = FastAPI(title="SentinelWard automation", version="0.2.0", docs_url=None)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready", response_model=None)
    async def ready() -> Response:
        payload = health.snapshot()
        code = status.HTTP_200_OK if health.ready else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(payload, status_code=code)

    @app.get("/metrics", response_class=PlainTextResponse)
    async def metrics() -> str:
        return health.prometheus_text()

    async def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        if service_token is None:
            raise HTTPException(status_code=503, detail="alert command API is not configured")
        scheme, _, supplied = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(supplied, service_token):
            raise HTTPException(status_code=401, detail="invalid service identity")

    @app.post("/internal/v1/alerts/{alert_id}/ack")
    async def acknowledge(
        alert_id: str,
        command: AlertCommand,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        await authorize(authorization)
        if alerts is None:
            raise HTTPException(status_code=503, detail="alert coordinator is unavailable")
        try:
            alert = await alerts.acknowledge(
                alert_id,
                by=command.by,
                at_ms=command.ts,
                event_id=command.event_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        wire = alert.wire()
        views = alert_output_views(wire)
        return {
            "alert": wire.model_dump(mode="json"),
            "summary": render_alert(wire),
            "outputs": views.as_dict(),
        }

    @app.post("/internal/v1/alerts/{alert_id}/escalate")
    async def escalate(
        alert_id: str,
        command: AlertCommand,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, object]:
        await authorize(authorization)
        if alerts is None:
            raise HTTPException(status_code=503, detail="alert coordinator is unavailable")
        try:
            alert = await alerts.escalate(
                alert_id,
                by=command.by,
                at_ms=command.ts,
                event_id=command.event_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        wire = alert.wire()
        views = alert_output_views(wire)
        return {
            "alert": wire.model_dump(mode="json"),
            "summary": render_alert(wire),
            "outputs": views.as_dict(),
        }

    return app
