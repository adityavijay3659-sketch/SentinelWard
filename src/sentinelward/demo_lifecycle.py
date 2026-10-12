"""Doc 00 v1.1 lifecycle around unchanged M6. Never score from a timer."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from sentinelward.contracts import DemoControlMessage, DemoSourceEnd, ScoreMessage, VitalsMessage
from sentinelward.m6 import MODEL_VERSION, EpisodeContext, M6Config, step
from sentinelward.m6_persistence import delivery_key, restored_state
from sentinelward.persistence import InMemoryStore

SCRIPT_SECONDS = 1200
SOURCE_END_SECONDS = {"B03": 330, "B04": 420, "B07": 870}
SOURCE_JOIN_SECONDS = {"B04": 90, "B07": 540}


class DemoBed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str
    context: EpisodeContext | None = None
    state: str = "offline"
    completed: bool = True
    offline_since: int | None = None
    source_end_ts: int | None = None
    source_start_ts: int | None = None
    latest: dict[str, Any] = Field(
        default_factory=lambda: {"hr": None, "spo2": None, "bp": None, "rr": None}
    )
    latest_ts: int | None = None
    last_seq: int = -1
    replay_cursor_s: int | None = None


class DemoRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str | None = None
    last_run_id: str | None = None
    active: bool = False
    start_ts: int | None = None
    start_at_s: int = 0
    last_control_ts: int = -1
    last_control_hash: str | None = None
    episode_start_highwater: int = -1
    frame_highwater: int = -1
    used_run_ids: list[str] = Field(default_factory=list)
    beds: dict[str, DemoBed] = Field(default_factory=dict)
    model_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    config: M6Config | None = None
    model_version: str | None = None


@dataclass
class DemoTransaction:
    runtime: DemoRuntime
    dirty: bool = False
    audits: list[dict[str, Any]] = field(default_factory=list)
    scores: list[tuple[str, ScoreMessage]] = field(default_factory=list)
    retire_run: str | None = None

    def audit(self, event: str, ts: int, bed_id: str | None = None) -> None:
        self.dirty = True
        self.audits.append(
            {
                "run_id": self.runtime.run_id or self.runtime.last_run_id,
                "event": event,
                "ts": ts,
                "bed_id": bed_id,
            }
        )


class DemoRepository(Protocol):
    def transaction(self) -> Any: ...


@dataclass
class InMemoryDemoRepository:
    store: InMemoryStore
    runtime: DemoRuntime = field(default_factory=DemoRuntime)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[DemoTransaction]:
        async with self._lock:
            unit = DemoTransaction(self.runtime.model_copy(deep=True))
            yield unit
            if not unit.dirty:
                return
            self.runtime = unit.runtime
            for event in unit.audits:
                self.store.audits.append(
                    {
                        "correlation_id": f"demo:{event['run_id']}",
                        "event_type": f"demo.{event['event']}",
                        "actor": "backend",
                        "detail": event,
                    }
                )
            if unit.retire_run is not None:
                for entry in self.store.outbox.values():
                    body = entry.get("payload", {}).get("body", {})
                    if (
                        body.get("model") == "M6"
                        and body.get("extra", {}).get("demo_run_id") == unit.retire_run
                        and entry["status"] in {"pending", "failed"}
                    ):
                        entry.update(
                            status="unknown", last_error="demo cycle closed; retained without retry"
                        )
            for key, score in unit.scores:
                topic = f"ward/bed/{score.bed_id}/score/M6"
                self.store.outbox.setdefault(
                    key,
                    {
                        "destination": f"mqtt:{topic}",
                        "payload": {
                            "topic": topic,
                            "body": score.model_dump(mode="json"),
                            "qos": 1,
                        },
                        "correlation_id": key,
                        "status": "pending",
                    },
                )


@dataclass(frozen=True)
class PostgresDemoRepository:
    database_url: str

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[DemoTransaction]:
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute("SELECT pg_advisory_xact_lock(6007, 1)")
            cursor = await connection.execute(
                "SELECT state FROM automation.demo_m6_runtime WHERE singleton_id = 1 FOR UPDATE"
            )
            row = await cursor.fetchone()
            unit = DemoTransaction(DemoRuntime.model_validate(row[0]) if row else DemoRuntime())
            yield unit
            if not unit.dirty:
                return
            await connection.execute(
                """
                INSERT INTO automation.demo_m6_runtime(singleton_id,state)
                VALUES (1,%s)
                ON CONFLICT(singleton_id) DO UPDATE
                SET state=EXCLUDED.state, updated_at=now()
                """,
                (Jsonb(unit.runtime.model_dump(mode="json")),),
            )
            for event in unit.audits:
                await connection.execute(
                    """
                    INSERT INTO automation.audit_events(
                        audit_id,occurred_at,correlation_id,event_type,actor,detail
                    ) VALUES (%s,now(),%s,%s,'backend',%s)
                    """,
                    (uuid4(), f"demo:{event['run_id']}", f"demo.{event['event']}", Jsonb(event)),
                )
            if unit.retire_run is not None:
                await connection.execute(
                    """
                    UPDATE automation.outbox_events
                    SET status='unknown',
                        last_error='demo cycle closed; retained without retry',
                        updated_at=now()
                    WHERE status IN ('pending','failed')
                      AND payload->'body'->>'model'='M6'
                      AND payload->'body'->'extra'->>'demo_run_id'=%s
                    """,
                    (unit.retire_run,),
                )
            for key, score in unit.scores:
                topic = f"ward/bed/{score.bed_id}/score/M6"
                await connection.execute(
                    """
                    INSERT INTO automation.outbox_events(
                        outbox_id,delivery_key,destination,payload,correlation_id,status,
                        attempt_count,next_attempt_at,created_at,updated_at
                    ) VALUES (%s,%s,%s,%s,%s,'pending',0,now(),now(),now())
                    ON CONFLICT(delivery_key) DO NOTHING
                    """,
                    (
                        uuid4(),
                        key,
                        f"mqtt:{topic}",
                        Jsonb({"topic": topic, "body": score.model_dump(mode="json"), "qos": 1}),
                        key,
                    ),
                )


@dataclass
class DemoM6Handler:
    repository: DemoRepository
    templates: dict[str, EpisodeContext]
    config: M6Config = field(default_factory=M6Config)
    clock_ms: Callable[[], int] = field(default=lambda: time.time_ns() // 1_000_000)

    def _check_config(self, unit: DemoTransaction) -> None:
        if unit.runtime.config is None:
            unit.runtime.config = self.config
            unit.runtime.model_version = MODEL_VERSION
            unit.dirty = True
        elif unit.runtime.config != self.config or unit.runtime.model_version != MODEL_VERSION:
            raise ValueError("demo M6 model/configuration changed; reset cannot change it")

    async def handle_control(self, command: DemoControlMessage) -> None:
        digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        async with self.repository.transaction() as unit:
            self._check_config(unit)
            runtime = unit.runtime
            if runtime.last_control_hash == digest:
                return
            if command.ts <= runtime.last_control_ts:
                raise ValueError("stale/out-of-order demo control")
            if command.cmd == "reset":
                expected = runtime.run_id or runtime.last_run_id
                if expected is not None and command.run_id != expected:
                    raise ValueError("reset run_id does not match the current demo cycle")
                unit.retire_run = runtime.run_id
                runtime.model_states.clear()
                for bed in runtime.beds.values():
                    bed.context = None
                    bed.completed = True
                    bed.state = "offline"
                    bed.offline_since = (
                        bed.offline_since if bed.offline_since is not None else command.ts
                    )
                    bed.source_end_ts = None
                    bed.source_start_ts = None
                    bed.last_seq = -1
                    bed.replay_cursor_s = None
                runtime.active = False
                runtime.run_id = None
                runtime.start_ts = None
                runtime.start_at_s = 0
                unit.audit("run_reset", command.ts)
            else:
                if command.run_id in runtime.used_run_ids:
                    raise ValueError("run_id has already been used; start a new demo identity")
                start = ((command.ts + 999) // 1000) * 1000
                if start <= max(runtime.frame_highwater, runtime.episode_start_highwater):
                    raise ValueError("new demo must start after the previous episode timeline")
                unit.retire_run = runtime.run_id
                runtime.model_states.clear()
                runtime.active = True
                runtime.run_id = runtime.last_run_id = command.run_id
                runtime.used_run_ids.append(command.run_id)
                runtime.start_ts = start
                runtime.episode_start_highwater = start
                runtime.start_at_s = command.start_at_s
                for previous in runtime.beds.values():
                    previous.context = None
                    previous.completed = True
                    previous.state = "offline"
                    previous.replay_cursor_s = None
                for bed_id, template in self.templates.items():
                    old = runtime.beds.get(bed_id)
                    identity = hashlib.sha256(f"{command.run_id}:{bed_id}".encode()).hexdigest()[
                        :48
                    ]
                    source_end = SOURCE_END_SECONDS.get(bed_id, SCRIPT_SECONDS)
                    join = SOURCE_JOIN_SECONDS.get(bed_id, 0)
                    context_start = start + max(0, join - command.start_at_s) * 1000
                    runtime.beds[bed_id] = DemoBed(
                        device_id=template.device_id,
                        context=EpisodeContext(
                            episode_id=f"demo:{identity}",
                            device_id=template.device_id,
                            start_ts=context_start,
                        ),
                        completed=command.start_at_s >= source_end,
                        offline_since=command.ts,
                        source_start_ts=context_start,
                        source_end_ts=start + max(0, source_end - command.start_at_s) * 1000,
                        latest=copy.deepcopy(old.latest)
                        if old
                        else {"hr": None, "spo2": None, "bp": None, "rr": None},
                        latest_ts=old.latest_ts if old else None,
                        replay_cursor_s=command.start_at_s,
                    )
                unit.audit("run_start", command.ts)
            runtime.last_control_ts = command.ts
            runtime.last_control_hash = digest
            unit.dirty = True

    @staticmethod
    def _complete(unit: DemoTransaction, bed_id: str, ts: int) -> None:
        bed = unit.runtime.beds[bed_id]
        if bed.completed:
            return
        bed.completed = True
        bed.state = "offline"
        bed.offline_since = ts
        unit.audit("source_end", ts, bed_id)

    @classmethod
    def _advance(cls, unit: DemoTransaction, now_ms: int) -> None:
        runtime = unit.runtime
        if not runtime.active:
            return
        for bed_id, bed in runtime.beds.items():
            if bed.source_end_ts is not None and now_ms >= bed.source_end_ts:
                cls._complete(unit, bed_id, bed.source_end_ts)
        if (
            runtime.start_ts is not None
            and now_ms >= runtime.start_ts + (SCRIPT_SECONDS - runtime.start_at_s) * 1000
        ):
            runtime.active = False
            unit.audit("run_end", now_ms)

    async def advance(self, now_ms: int | None = None) -> None:
        async with self.repository.transaction() as unit:
            self._check_config(unit)
            self._advance(unit, self.clock_ms() if now_ms is None else now_ms)

    async def source_end(self, event: DemoSourceEnd) -> None:
        async with self.repository.transaction() as unit:
            self._check_config(unit)
            runtime = unit.runtime
            if event.run_id != runtime.run_id:
                raise ValueError("source_end belongs to a different demo cycle")
            bed = runtime.beds.get(event.bed_id)
            if bed is None or bed.device_id != event.device_id:
                raise ValueError("source_end bed/device is not configured")
            if (
                bed.context is None
                or event.ts < bed.context.start_ts
                or (bed.latest_ts is not None and event.ts <= bed.latest_ts)
            ):
                raise ValueError("source_end precedes the current episode data")
            self._complete(unit, event.bed_id, event.ts)

    async def handle_m6(self, message: VitalsMessage | ScoreMessage) -> ScoreMessage | None:
        await self.advance()
        async with self.repository.transaction() as unit:
            self._check_config(unit)
            runtime = unit.runtime
            bed = runtime.beds.get(message.bed_id)
            if not runtime.active or bed is None or bed.context is None or bed.completed:
                raise ValueError("demo bed is offline/reset; a valid new run is required")
            timestamp = message.ts if isinstance(message, VitalsMessage) else message.window_start
            if timestamp < bed.context.start_ts:
                raise ValueError("stale message from before the current demo episode")
            if bed.source_end_ts is not None and timestamp >= bed.source_end_ts:
                raise ValueError("message is beyond this recording's declared end")
            if isinstance(message, VitalsMessage) and message.device_id != bed.device_id:
                raise ValueError("demo device does not match the episode")
            state = restored_state(
                runtime.model_states.get(message.bed_id), bed.context, self.config
            )
            score = step(state, message)
            runtime.model_states[message.bed_id] = state.model_dump(mode="json")
            if isinstance(message, VitalsMessage) and message.ts > (
                bed.latest_ts if bed.last_seq >= 0 and bed.latest_ts is not None else -1
            ):
                bed.state = "live"
                bed.offline_since = None
                bed.latest.update(hr=message.hr, spo2=message.spo2, rr=message.rr)
                if message.nibp is not None:
                    bed.latest["bp"] = message.nibp.model_dump(mode="json")
                bed.latest_ts = message.ts
                bed.last_seq = message.seq
                assert runtime.start_ts is not None
                bed.replay_cursor_s = (
                    runtime.start_at_s + (message.ts - runtime.start_ts) // 1000 + 1
                )
                runtime.frame_highwater = max(runtime.frame_highwater, message.ts)
            if score is not None:
                score = score.model_copy(
                    update={
                        "extra": {
                            **score.extra,
                            "demo_run_id": runtime.run_id,
                            "episode_id": bed.context.episode_id,
                            "demo_only": True,
                        }
                    }
                )
                unit.scores.append((delivery_key(bed.context, score), score))
            unit.dirty = True
            return score

    async def snapshot(self) -> dict[str, Any]:
        async with self.repository.transaction() as unit:
            self._check_config(unit)
            self._advance(unit, self.clock_ms())
            runtime = unit.runtime
            return {
                "v": 1,
                "run_id": runtime.run_id,
                "active": runtime.active,
                "start_at_s": runtime.start_at_s,
                "model_version": MODEL_VERSION,
                "m6_config": self.config.model_dump(),
                "beds": [
                    {
                        "bed_id": key,
                        "device_id": bed.device_id,
                        "state": bed.state,
                        "offline_since": bed.offline_since,
                        "latest": copy.deepcopy(bed.latest),
                        "latest_ts": bed.latest_ts,
                        "recording_complete": bed.completed,
                        "episode_id": bed.context.episode_id if bed.context else None,
                        "replay_cursor_s": bed.replay_cursor_s,
                    }
                    for key, bed in sorted(runtime.beds.items())
                ],
            }


async def monitor_demo_lifecycle(handler: DemoM6Handler) -> None:
    while True:
        await handler.advance()
        await asyncio.sleep(1)
