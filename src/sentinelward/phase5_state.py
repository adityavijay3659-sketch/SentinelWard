"""Short, serialized state/audit/outbox transactions and normalized entities."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ConfigDict, Field

from sentinelward.contracts import StrictMessage
from sentinelward.persistence import InMemoryStore
from sentinelward.phase5_contracts import digest


class Runtime(StrictMessage):
    model_config = ConfigDict(extra="forbid", frozen=False)
    run_id: str | None = None
    active: bool = False
    start_ts: int = 0
    end_ts: int = 0
    start_at_s: int = 0
    control_ts: int = -1
    control_hash: str = ""
    used_runs: list[str] = Field(default_factory=list)
    workload_minute: int = -1
    demo_briefing: bool = False
    shift_boundary: int = 0


@dataclass
class Unit:
    runtime: Runtime
    rows: dict[tuple[str, str], dict[str, Any]]
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    audits: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    retire_run: str | None = None

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        value = self.rows.get((kind, key))
        return value if value is not None and value["run_id"] == self.runtime.run_id else None

    def put(self, kind: str, key: str, value: dict[str, Any]) -> None:
        if value.get("run_id") != self.runtime.run_id:
            raise ValueError("entity run mismatch")
        self.rows[kind, key] = copy.deepcopy(value)

    def list(self, kind: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (key, value)
            for (row_kind, key), value in self.rows.items()
            if row_kind == kind and value["run_id"] == self.runtime.run_id
        ]


class Repository(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[Unit]: ...


@dataclass
class MemoryRepository:
    store: InMemoryStore
    runtime: Runtime = field(default_factory=Runtime)
    history: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Unit]:
        async with self.lock:
            unit = Unit(
                self.runtime.model_copy(deep=True),
                {
                    (kind, key): copy.deepcopy(value)
                    for (run, kind, key), value in self.history.items()
                    if run == self.runtime.run_id
                },
            )
            yield unit
            self.runtime = unit.runtime
            for (kind, key), value in unit.rows.items():
                self.history[value["run_id"], kind, key] = copy.deepcopy(value)
            if unit.retire_run:
                for event in self.store.outbox.values():
                    if event.get("correlation_id") == f"phase5:{unit.retire_run}" and event[
                        "status"
                    ] in {"pending", "failed"}:
                        event.update(
                            status="unknown", last_error="retired Phase 5 run; audit retained"
                        )
            for name, actor, body in unit.audits:
                await self.store.append_audit(
                    correlation_id=f"phase5:{unit.runtime.run_id}",
                    event_type=name,
                    actor=actor,
                    detail=body,
                )
            for topic, body in unit.events:
                await self.store.enqueue_outbox(
                    delivery_key="p5:" + digest([topic, body]),
                    destination="mqtt:" + topic,
                    payload={"topic": topic, "body": body, "qos": 1},
                    correlation_id=f"phase5:{unit.runtime.run_id}",
                )


@dataclass(frozen=True)
class PostgresRepository:
    database_url: str

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Unit]:
        async with await psycopg.AsyncConnection.connect(self.database_url) as db:
            await db.execute("SELECT pg_advisory_xact_lock(6007,5)")
            cur = await db.execute(
                "SELECT state FROM automation.phase5_runtime WHERE singleton_id=1"
            )
            meta = await cur.fetchone()
            runtime = Runtime.model_validate(meta[0]) if meta else Runtime()
            cur = await db.execute(
                "SELECT kind,item_id,body FROM automation.phase5_items WHERE run_id=%s",
                (runtime.run_id,),
            )
            rows = {(kind, key): body for kind, key, body in await cur.fetchall()}
            original = copy.deepcopy(rows)
            unit = Unit(runtime, rows)
            yield unit
            await db.execute(
                """INSERT INTO automation.phase5_runtime VALUES(1,%s)
                ON CONFLICT(singleton_id) DO UPDATE SET state=EXCLUDED.state""",
                (Jsonb(unit.runtime.model_dump(mode="json")),),
            )
            for (kind, key), body in unit.rows.items():
                if original.get((kind, key)) != body:
                    await db.execute(
                        """INSERT INTO automation.phase5_items(kind,item_id,run_id,body)
                        VALUES(%s,%s,%s,%s) ON CONFLICT(run_id,kind,item_id)
                        DO UPDATE SET body=EXCLUDED.body,updated_at=now()""",
                        (kind, key, body["run_id"], Jsonb(body)),
                    )
            if unit.retire_run:
                await db.execute(
                    """UPDATE automation.outbox_events SET status='unknown',
                    last_error='retired Phase 5 run; audit retained',updated_at=now()
                    WHERE correlation_id=%s AND status IN ('pending','failed')""",
                    (f"phase5:{unit.retire_run}",),
                )
            for name, actor, body in unit.audits:
                await db.execute(
                    """INSERT INTO automation.audit_events
                    (audit_id,occurred_at,correlation_id,event_type,actor,detail)
                    VALUES(%s,now(),%s,%s,%s,%s)""",
                    (uuid4(), f"phase5:{runtime.run_id}", name, actor, Jsonb(body)),
                )
            for _, receipt in unit.list("undo"):
                await db.execute(
                    """INSERT INTO automation.undo_links
                    (undo_action_id,original_action_id,approved_by)
                    VALUES(%s,%s,%s) ON CONFLICT(original_action_id) DO NOTHING""",
                    (
                        receipt["undo_action_id"],
                        receipt["original_action_id"],
                        receipt["approved_by"],
                    ),
                )
            for topic, body in unit.events:
                await db.execute(
                    """INSERT INTO automation.outbox_events
                    (outbox_id,delivery_key,destination,payload,correlation_id,status,
                    attempt_count,next_attempt_at,created_at,updated_at)
                    VALUES(%s,%s,%s,%s,%s,'pending',0,now(),now(),now())
                    ON CONFLICT(delivery_key) DO NOTHING""",
                    (
                        uuid4(),
                        "p5:" + digest([topic, body]),
                        "mqtt:" + topic,
                        Jsonb({"topic": topic, "body": body, "qos": 1}),
                        f"phase5:{runtime.run_id}",
                    ),
                )
