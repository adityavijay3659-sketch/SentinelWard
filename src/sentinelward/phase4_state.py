"""Typed state plus atomic state/audit/outbox transactions for Phase 4."""

from __future__ import annotations

import asyncio
import copy
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import Field

from sentinelward.contracts import BedId, DeviceId, Identifier, StaffId, StrictMessage
from sentinelward.persistence import InMemoryStore


def identity(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


class Device(StrictMessage):
    device_id: DeviceId
    bed_id: BedId
    username: Identifier
    client_id: Identifier
    model: Identifier
    firmware: Identifier
    lab_owned: bool = False


class ContainmentPolicy(StrictMessage):
    version: Identifier
    threshold: float = Field(ge=0, le=1)
    comparator: Literal[">", ">="] = ">="
    approved: bool = False

    def accepts(self, confidence: float) -> bool:
        return (
            confidence >= self.threshold if self.comparator == ">=" else confidence > self.threshold
        )


class Authorization(StrictMessage):
    request_id: Identifier
    by: StaffId
    role: Literal["it", "biomed", "nurse"]
    action: Identifier
    target_id: Identifier
    run_id: Identifier
    expires_ts: int = Field(ge=0)


@dataclass
class AgentState:
    run_id: str | None = None
    start_ts: int = 0
    active: bool = False
    control_ts: int = -1
    control_digest: str = ""
    used_runs: list[str] = field(default_factory=list)
    start_at_s: int = 0
    highwater: dict[str, int] = field(default_factory=dict)
    offline: dict[str, int] = field(default_factory=dict)
    latest: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_trusted: dict[str, dict[str, Any]] = field(default_factory=dict)
    untrusted: list[str] = field(default_factory=list)
    loose_active: list[str] = field(default_factory=list)
    loose_starts: dict[str, list[int]] = field(default_factory=dict)
    drift_active: list[str] = field(default_factory=list)
    fault_history: list[dict[str, Any]] = field(default_factory=list)
    tickets: dict[str, dict[str, Any]] = field(default_factory=dict)
    incidents: dict[str, dict[str, Any]] = field(default_factory=dict)
    incident_by_device: dict[str, str] = field(default_factory=dict)
    effects: dict[str, dict[str, Any]] = field(default_factory=dict)
    authorizations: dict[str, dict[str, Any]] = field(default_factory=dict)
    undo_links: dict[str, str] = field(default_factory=dict)
    watches: dict[str, dict[str, Any]] = field(default_factory=dict)
    buffers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    bed_projections: dict[str, dict[str, Any]] = field(default_factory=dict)
    effective_watches: dict[str, list[str]] = field(default_factory=dict)
    ticket_highwater: dict[str, int] = field(default_factory=dict)
    watch_generation: int = 0
    reconnect_ts: dict[str, int] = field(default_factory=dict)
    active_containment: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentTransaction:
    state: AgentState
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    audits: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    retire_run: str | None = None

    def publish(self, topic: str, body: dict[str, Any]) -> None:
        self.events.append((topic, body))


class AgentRepository(Protocol):
    def transaction(self) -> Any: ...


@dataclass
class MemoryAgentRepository:
    store: InMemoryStore
    state: AgentState = field(default_factory=AgentState)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AgentTransaction]:
        async with self.lock:
            unit = AgentTransaction(copy.deepcopy(self.state))
            yield unit
            self.state = unit.state
            if unit.retire_run is not None:
                for entry in self.store.outbox.values():
                    if entry.get("correlation_id") == f"phase4:{unit.retire_run}" and entry[
                        "status"
                    ] in {"pending", "failed"}:
                        entry.update(
                            status="unknown", last_error="old agent run retired; history preserved"
                        )
            for event, actor, body in unit.audits:
                await self.store.append_audit(
                    correlation_id=f"phase4:{unit.state.run_id}",
                    event_type=event,
                    actor=actor,
                    detail=body,
                )
            for topic, body in unit.events:
                import json

                key = "p4:" + identity(topic, json.dumps(body, sort_keys=True, allow_nan=False))
                await self.store.enqueue_outbox(
                    delivery_key=key,
                    destination=f"mqtt:{topic}",
                    payload={"topic": topic, "body": body, "qos": 1},
                    correlation_id=f"phase4:{unit.state.run_id}",
                )


@dataclass(frozen=True)
class PostgresAgentRepository:
    database_url: str

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AgentTransaction]:
        import json

        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute("SELECT pg_advisory_xact_lock(6007,4)")
            cursor = await connection.execute(
                "SELECT state FROM automation.phase4_runtime WHERE singleton_id=1 FOR UPDATE"
            )
            row = await cursor.fetchone()
            unit = AgentTransaction(AgentState(**row[0]) if row else AgentState())
            yield unit
            from dataclasses import asdict

            if unit.retire_run is not None:
                await connection.execute(
                    """UPDATE automation.outbox_events SET status='unknown',updated_at=now(),
                    last_error='old agent run retired; history preserved'
                    WHERE correlation_id=%s AND status IN ('pending','failed')""",
                    (f"phase4:{unit.retire_run}",),
                )

            await connection.execute(
                """INSERT INTO automation.phase4_runtime(singleton_id,state) VALUES(1,%s)
                ON CONFLICT(singleton_id) DO UPDATE SET state=EXCLUDED.state,updated_at=now()""",
                (Jsonb(asdict(unit.state)),),
            )
            for original_id, undo_id in unit.state.undo_links.items():
                undo = next(
                    (
                        effect
                        for effect in unit.state.effects.values()
                        if effect["action_id"] == undo_id
                    ),
                    None,
                )
                if undo is not None:
                    await connection.execute(
                        """INSERT INTO automation.undo_links
                        (undo_action_id,original_action_id,approved_by)
                        VALUES(%s,%s,%s) ON CONFLICT(original_action_id) DO NOTHING""",
                        (undo_id, original_id, undo["approved_by"]),
                    )
            for event, actor, body in unit.audits:
                await connection.execute(
                    """INSERT INTO automation.audit_events
                    (audit_id,occurred_at,correlation_id,event_type,actor,detail)
                    VALUES(%s,now(),%s,%s,%s,%s)""",
                    (uuid4(), f"phase4:{unit.state.run_id}", event, actor, Jsonb(body)),
                )
            for topic, body in unit.events:
                key = "p4:" + identity(topic, json.dumps(body, sort_keys=True, allow_nan=False))
                await connection.execute(
                    """INSERT INTO automation.outbox_events
                    (outbox_id,delivery_key,destination,payload,correlation_id,status,
                    attempt_count,next_attempt_at,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,'pending',0,now(),now(),now())
                    ON CONFLICT(delivery_key) DO NOTHING""",
                    (
                        uuid4(),
                        key,
                        f"mqtt:{topic}",
                        Jsonb({"topic": topic, "body": body, "qos": 1}),
                        f"phase4:{unit.state.run_id}",
                    ),
                )
