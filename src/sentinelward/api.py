from __future__ import annotations

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse

from sentinelward.health import HealthRegistry


def create_app(health: HealthRegistry) -> FastAPI:
    app = FastAPI(title="SentinelWard automation", version="0.1.0", docs_url=None)

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

    return app
