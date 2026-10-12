"""Backend reference application, mounted only by the isolated Phase 4 profile."""

from __future__ import annotations

import asyncio
import copy
import secrets
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from sentinelward.contracts import RecordMessage
from sentinelward.phase4 import Phase4Coordinator
from sentinelward.phase4_state import Authorization


class RecordProjection:
    def __init__(self) -> None:
        self.records: dict[str, RecordMessage] = {}
        self.lock = asyncio.Lock()

    async def consume(self, message: RecordMessage, run_id: str | None) -> bool:
        async with self.lock:
            revision = message.data.get("revision")
            if message.kind not in {"incident", "ticket"} or message.data.get("run_id") != run_id:
                return False
            if type(revision) is not int or revision < 1:
                return False
            prior = self.records.get(message.record_id)
            if prior is not None and revision <= prior.data["revision"]:
                return False
            self.records[message.record_id] = message.model_copy(deep=True)
            return True


class ReferenceTicketEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["new", "in_progress", "done"]
    expected_revision: int = Field(ge=1)
    note: str = Field(default="", max_length=240)


def create_reference_backend(
    agent: Phase4Coordinator,
    *,
    service_token: str,
    staff_tokens: dict[str, tuple[str, str]] | None = None,
) -> FastAPI:
    app = FastAPI(title="TEST ONLY Phase 4 backend reference", docs_url=None)
    projection = RecordProjection()
    app.state.record_projection = projection

    def principal(header: str | None, *, service: bool = False) -> tuple[str, str]:
        scheme, _, token = (header or "").partition(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="authentication required")
        if secrets.compare_digest(token, service_token):
            return ("backend", "service")
        if not service:
            for known, actor in (staff_tokens or {}).items():
                if secrets.compare_digest(token, known):
                    return actor
        raise HTTPException(status_code=401, detail="invalid reference identity")

    @app.post("/internal/v1/reference/records")
    async def consume_record(
        record: RecordMessage, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, object]:
        principal(authorization, service=True)
        state = await agent.snapshot()
        accepted = await projection.consume(record, state["run_id"] if state["active"] else None)
        return {"reference_only": True, "accepted": accepted}

    @app.get("/api/ward")
    async def ward(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        principal(authorization)
        await agent.advance()
        state = await agent.snapshot()
        beds = [
            {
                "bed_id": device.bed_id,
                "device_id": device.device_id,
                "latest": copy.deepcopy(state["latest"].get(device.bed_id, {})),
                **copy.deepcopy(state["bed_projections"].get(device.bed_id, {})),
            }
            for device in agent.inventory.values()
        ]
        return {"reference_only": True, "run_id": state["run_id"], "beds": beds}

    @app.get("/api/tickets")
    async def tickets(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        principal(authorization)
        state = await agent.snapshot()
        return {
            "reference_only": True,
            "tickets": [
                {"record_id": key, **copy.deepcopy(value)}
                for key, value in state["tickets"].items()
                if value["run_id"] == state["run_id"] and state["active"]
            ],
        }

    @app.patch("/api/tickets/{ticket_id}")
    async def edit_ticket(
        ticket_id: str,
        command: ReferenceTicketEdit,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        actor, role = principal(authorization)
        if role != "biomed":
            raise HTTPException(status_code=403, detail="biomed identity required")
        state = await agent.snapshot()
        if not state["run_id"]:
            raise HTTPException(status_code=409, detail="no active run")
        auth = Authorization(
            request_id=f"ticket-edit:{ticket_id}:{command.expected_revision}",
            by=actor,
            role="biomed",
            action="ticket_status",
            target_id=ticket_id,
            run_id=state["run_id"],
            expires_ts=agent.clock_ms() + 1000,
        )
        try:
            result = await agent.set_ticket_status(
                ticket_id,
                authorization=auth,
                status=command.status,
                expected_revision=command.expected_revision,
                note=command.note,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"reference_only": True, "ticket": result}

    @app.get("/api/actions")
    async def actions(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        principal(authorization)
        state = await agent.snapshot()
        return {
            "reference_only": True,
            "actions": [
                copy.deepcopy(e)
                for e in state["effects"].values()
                if e.get("run_id") == state["run_id"]
            ],
        }

    @app.get("/api/incidents/{incident_id}")
    async def incident(
        incident_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        principal(authorization)
        state = await agent.snapshot()
        data = state["incidents"].get(incident_id)
        if not data or data["run_id"] != state["run_id"]:
            raise HTTPException(status_code=404, detail="current incident not found")
        return {
            "reference_only": True,
            "incident": {k: v for k, v in data.items() if k != "snapshot"},
        }

    return app
