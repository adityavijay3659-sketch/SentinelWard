from __future__ import annotations

import os
import time
from uuid import uuid4

import psycopg
import pytest

from sentinelward.contracts import DemoControlMessage, VitalsMessage
from sentinelward.demo_lifecycle import DemoM6Handler, DemoRuntime, PostgresDemoRepository
from sentinelward.m6 import MODEL_VERSION, EpisodeContext, M6Config
from sentinelward.m6_demo import synthetic_frame

DATABASE_URL = os.getenv("SENTINEL_TEST_DATABASE_URL")


def _frame(base: int, second: int) -> VitalsMessage:
    body = synthetic_frame(second, bed_id="B03").model_dump(mode="json")
    body["ts"] = base + second * 1000
    if body["nibp"] is not None:
        body["nibp"]["ts"] = body["ts"]
    return VitalsMessage.model_validate(body)


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="SENTINEL_TEST_DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_postgres_demo_reset_is_atomic_durable_and_preserves_history() -> None:
    assert DATABASE_URL is not None
    repository = PostgresDemoRepository(DATABASE_URL)
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        cursor = await connection.execute(
            "SELECT state FROM automation.demo_m6_runtime WHERE singleton_id=1"
        )
        row = await cursor.fetchone()
    prior = DemoRuntime.model_validate(row[0]) if row else DemoRuntime()
    lower_bound = max(
        time.time_ns() // 1_000_000,
        prior.frame_highwater + 10_000,
        prior.episode_start_highwater + 10_000,
        prior.last_control_ts + 10_000,
    )
    base = ((lower_bound + 4_999) // 5_000) * 5_000
    run_id = f"integration_{uuid4().hex}"
    handler = DemoM6Handler(
        repository,
        {"B03": EpisodeContext(episode_id="template", device_id="MON-03", start_ts=0)},
        clock_ms=lambda: base,
    )
    await handler.handle_control(
        DemoControlMessage(
            v=1,
            type="demo_control",
            ts=base,
            cmd="run",
            run_id=run_id,
            start_at_s=0,
        )
    )
    for second in range(10):
        await handler.handle_m6(_frame(base, second))

    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        cursor = await connection.execute(
            "SELECT count(*) FROM automation.audit_events WHERE correlation_id=%s",
            (f"demo:{run_id}",),
        )
        audits_before = (await cursor.fetchone())[0]
        cursor = await connection.execute(
            """
            SELECT count(*) FROM automation.outbox_events
            WHERE payload->'body'->'extra'->>'demo_run_id'=%s
            """,
            (run_id,),
        )
        assert (await cursor.fetchone())[0] == 1

    reset = DemoControlMessage(
        v=1,
        type="demo_control",
        ts=base + 20_000,
        cmd="reset",
        run_id=run_id,
        start_at_s=0,
    )
    await handler.handle_control(reset)
    await handler.handle_control(reset)

    restarted = DemoM6Handler(
        PostgresDemoRepository(DATABASE_URL),
        {"B03": EpisodeContext(episode_id="template", device_id="MON-03", start_ts=0)},
        clock_ms=lambda: base + 20_000,
    )
    snapshot = await restarted.snapshot()
    assert snapshot["active"] is False
    assert snapshot["model_version"] == MODEL_VERSION
    assert snapshot["m6_config"] == M6Config().model_dump()
    assert snapshot["beds"][0]["episode_id"] is None

    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        cursor = await connection.execute(
            "SELECT state FROM automation.demo_m6_runtime WHERE singleton_id=1"
        )
        runtime = DemoRuntime.model_validate((await cursor.fetchone())[0])
        assert runtime.model_states == {}
        cursor = await connection.execute(
            "SELECT count(*) FROM automation.audit_events WHERE correlation_id=%s",
            (f"demo:{run_id}",),
        )
        assert (await cursor.fetchone())[0] == audits_before + 1
        cursor = await connection.execute(
            """
            SELECT status FROM automation.outbox_events
            WHERE payload->'body'->'extra'->>'demo_run_id'=%s
            """,
            (run_id,),
        )
        assert (await cursor.fetchone())[0] == "unknown"
