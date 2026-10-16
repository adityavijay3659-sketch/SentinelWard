"""Human authority comes from trusted grants or server-bound lab identities."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Response

from sentinelward.phase5 import Phase5Coordinator
from sentinelward.phase5_contracts import (
    ConfirmReport,
    CoverageReceipt,
    EditReport,
    GenerateBriefing,
    HumanCommand,
    HumanGrant,
    MarkSent,
    Principal,
    SuppressionReceipt,
)


def router(agent: Phase5Coordinator, *, token: str) -> APIRouter:
    routes = APIRouter(prefix="/internal/v1/phase5")

    def authorized(header: str | None) -> None:
        scheme, _, credential = (header or "").partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(credential, token):
            raise HTTPException(status_code=401, detail="service authentication required")

    async def call(operation: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await operation()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @routes.post("/authorizations")
    async def grant(
        body: HumanGrant, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, str]:
        authorized(authorization)
        await call(lambda: agent.register_grant(body))
        return {"status": "registered"}

    @routes.get("/status")
    async def status(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        authorized(authorization)
        return await agent.status()

    @routes.post("/incidents/{incident_id}/confirm-report")
    async def confirm(
        incident_id: str, body: ConfirmReport, authorization: Annotated[str | None, Header()] = None
    ) -> Any:
        authorized(authorization)
        return await call(lambda: agent.confirm_report(incident_id, body))

    @routes.patch("/reports/{report_id}")
    async def edit(
        report_id: str, body: EditReport, authorization: Annotated[str | None, Header()] = None
    ) -> Any:
        authorized(authorization)
        return await call(lambda: agent.edit_report(report_id, body))

    @routes.post("/reports/{report_id}/mark-sent")
    async def mark_sent(
        report_id: str, body: MarkSent, authorization: Annotated[str | None, Header()] = None
    ) -> Any:
        authorized(authorization)
        return await call(lambda: agent.mark_sent(report_id, body))

    @routes.get("/reports/{report_id}/pdf")
    async def pdf(
        report_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> Response:
        authorized(authorization)
        body, metadata = await call(lambda: agent.pdf(report_id))
        return Response(
            body,
            media_type="application/pdf",
            headers={
                "X-Document-SHA256": metadata["sha256"],
                "X-Report-Revision": str(metadata["revision"]),
            },
        )

    @routes.post("/briefings")
    async def briefing(
        body: GenerateBriefing, authorization: Annotated[str | None, Header()] = None
    ) -> Any:
        authorized(authorization)
        return await call(lambda: agent.generate_briefing(body))

    @routes.post("/actions/{action_id}/undo")
    async def undo(
        action_id: str, body: HumanCommand, authorization: Annotated[str | None, Header()] = None
    ) -> Any:
        authorized(authorization)
        return await call(lambda: agent.undo(action_id, body))

    @routes.post("/coverage")
    async def coverage(
        body: CoverageReceipt, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, str]:
        authorized(authorization)
        await call(lambda: agent.ingest_coverage(body))
        return {"status": "recorded"}

    @routes.post("/suppression")
    async def suppression(
        body: SuppressionReceipt, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, str]:
        authorized(authorization)
        await call(lambda: agent.ingest_suppression(body))
        return {"status": "recorded"}

    return routes


def reference_router(
    agent: Phase5Coordinator, *, staff_tokens: dict[str, tuple[str, str]]
) -> APIRouter:
    routes = APIRouter()

    def principal(header: str | None, roles: set[str]) -> Principal:
        scheme, _, token = (header or "").partition(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="staff authentication required")
        for known, (actor, role) in staff_tokens.items():
            if secrets.compare_digest(token, known):
                if role not in roles:
                    raise HTTPException(status_code=403, detail="staff role denied")
                return Principal.model_validate({"by": actor, "role": role})
        raise HTTPException(status_code=401, detail="unknown staff identity")

    async def authorize_command(
        body: HumanCommand, person: Principal, action: str, target: str
    ) -> None:
        if body.by != person.by:
            raise HTTPException(status_code=403, detail="actor does not match session")
        grant = HumanGrant.model_validate(
            {
                "request_id": body.request_id,
                "principal": person.model_dump(mode="json"),
                "run_id": body.run_id,
                "action": action,
                "target_id": target,
                "expires_ts": body.ts + 10_000,
            }
        )
        await agent.register_grant(grant)

    async def call(operation: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await operation()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @routes.get("/api/reports/{report_id}")
    async def report(
        report_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        principal(authorization, {"it"})
        state = await agent.status()
        found = next((r for r in state["records"]["report"] if r["record_id"] == report_id), None)
        if found is None:
            raise HTTPException(status_code=404, detail="current report not found")
        return {
            "reference_only": True,
            "report": found,
            "generation": next(
                (j for j in reversed(state["jobs"]) if j["record_id"] == report_id), None
            ),
            "remaining_ms": max(0, found["deadline_ts"] - agent.clock_ms()),
            "overdue": agent.clock_ms() >= found["deadline_ts"],
        }

    @routes.post("/api/incidents/{incident_id}/report")
    async def confirm(
        incident_id: str, body: ConfirmReport, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        person = principal(authorization, {"it"})
        await call(lambda: authorize_command(body, person, "confirm_report", incident_id))
        return {
            "reference_only": True,
            "report": await call(lambda: agent.confirm_report(incident_id, body)),
        }

    @routes.patch("/api/reports/{report_id}")
    async def edit(
        report_id: str, body: EditReport, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        person = principal(authorization, {"it"})
        await call(lambda: authorize_command(body, person, "edit_report", report_id))
        return {
            "reference_only": True,
            "report": await call(lambda: agent.edit_report(report_id, body)),
        }

    @routes.post("/api/reports/{report_id}/mark-sent")
    async def mark(
        report_id: str, body: MarkSent, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        person = principal(authorization, {"it"})
        await call(lambda: authorize_command(body, person, "mark_report_sent", report_id))
        return {
            "reference_only": True,
            "report": await call(lambda: agent.mark_sent(report_id, body)),
        }

    @routes.get("/api/reports/{report_id}/pdf")
    async def pdf(
        report_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> Response:
        principal(authorization, {"it"})
        content, meta = await call(lambda: agent.pdf(report_id))
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "X-Document-SHA256": meta["sha256"],
                "X-Report-Revision": str(meta["revision"]),
            },
        )

    @routes.get("/api/briefing")
    async def briefing(
        since: int | None = None, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        principal(authorization, {"nurse", "doctor"})
        state = await agent.status()
        records = [
            r
            for r in state["records"]["briefing"]
            if r["status"] == "ready" and (since is None or r["since"] == since)
        ]
        current = max(records, key=lambda r: (r["as_of"], r["revision"])) if records else None
        return {
            "reference_only": True,
            "briefing": current,
            "current_urgent": state["urgent"],
            "generation": next(
                (
                    j
                    for j in reversed(state["jobs"])
                    if current and j["record_id"] == current["record_id"]
                ),
                None,
            ),
        }

    @routes.post("/api/briefing/generate")
    async def generate(
        body: GenerateBriefing, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        person = principal(authorization, {"nurse", "doctor"})
        await call(lambda: authorize_command(body, person, "briefing", "WARD"))
        return {
            "reference_only": True,
            "briefing": await call(lambda: agent.generate_briefing(body)),
        }

    @routes.get("/api/workload")
    async def workload(
        hours: int = 2, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        principal(authorization, {"nurse", "doctor"})
        if hours != 2:
            raise HTTPException(status_code=422, detail="only two-hour policy is supported")
        await agent.advance()
        state = await agent.status()
        return {"reference_only": True, "workload": state["records"]["workload"]}

    return routes
