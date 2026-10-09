from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import psycopg
import pytest

from sentinelward.adapters.alert_publisher import MqttOutboxWorker
from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.config import Settings
from sentinelward.contracts import ScoreMessage
from sentinelward.engine import AutomationEngine
from sentinelward.health import HealthRegistry
from sentinelward.m6 import EpisodeContext
from sentinelward.m6_demo import synthetic_frame
from sentinelward.m6_persistence import InMemoryM6Handler, PostgresM6Handler
from sentinelward.persistence import InMemoryStore, PostgresStore
from sentinelward.service import MessageService

DATABASE_URL = os.getenv("SENTINEL_TEST_DATABASE_URL")


@pytest.mark.asyncio
async def test_service_dispatches_m6_without_running_actions_and_rejects_unknown_episode() -> None:
    store = InMemoryStore()
    actions = SimulatedActionPort()
    handler = InMemoryM6Handler(
        {"B01": EpisodeContext(episode_id="test", device_id="MON-01", start_ts=0)}
    )
    service = MessageService(
        Settings(mqtt_tls=False),
        store,
        AutomationEngine(store=store, action_port=actions),
        HealthRegistry(),
        m6_handler=handler,
    )
    for second in range(10):
        assert await service.handle(
            "ward/bed/B01/vitals", synthetic_frame(second).model_dump_json().encode()
        )
    assert len(handler.outbox) == 1 and actions.calls == []
    payload = synthetic_frame(9).model_dump_json().encode()
    assert await service.handle("ward/bed/B01/vitals", payload)
    assert len(handler.outbox) == 1 and service.health.counters["duplicate"] == 1
    assert await service.handle(
        "ward/bed/B02/vitals", synthetic_frame(0, bed_id="B02").model_dump_json().encode()
    )
    assert store.dead_letters[-1]["code"] == "M6_CONTEXT_REJECTED"


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="SENTINEL_TEST_DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_postgres_atomic_state_outbox_restart_and_concurrent_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        cursor = await connection.execute(
            "SELECT state FROM automation.m6_states WHERE bed_id='B12'"
        )
        previous = await cursor.fetchone()
    start_ts = (int(previous[0]["last_ts"]) // 10_000 + 1) * 10_000 if previous else 2_000_000
    context = EpisodeContext(episode_id=f"pg-{uuid4().hex}", device_id="MON-12", start_ts=start_ts)
    handler = PostgresM6Handler(DATABASE_URL, {"B12": context})

    def frame(second: int):
        return synthetic_frame(second, bed_id="B12").model_copy(
            update={"ts": context.start_ts + second * 1000, "nibp": None}
        )

    for second in range(9):
        await handler.handle_m6(frame(second))

    def fail_enqueue(context: EpisodeContext, score: ScoreMessage) -> str:
        del context, score
        raise RuntimeError("controlled failure after state write before outbox")

    with monkeypatch.context() as patch:
        patch.setattr("sentinelward.m6_persistence.delivery_key", fail_enqueue)
        with pytest.raises(RuntimeError, match="controlled failure"):
            await handler.handle_m6(frame(9))
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        cursor = await connection.execute(
            "SELECT state FROM automation.m6_states WHERE bed_id='B12'"
        )
        row = await cursor.fetchone()
        assert row is not None and row[0]["last_seq"] == 8
    restarted = PostgresM6Handler(DATABASE_URL, {"B12": context})
    results = await asyncio.gather(*(restarted.handle_m6(frame(9)) for _ in range(12)))
    assert sum(result is not None for result in results) == 1
    store = PostgresStore(DATABASE_URL)
    events = [
        event
        for event in await store.due_mqtt_outbox()
        if str(event["delivery_key"]).startswith("m6:")
        and event["payload"]["topic"] == "ward/bed/B12/score/M6"
        and event["payload"]["body"]["window_start"] == context.start_ts
    ]
    assert len(events) == 1
    assert events[0]["payload"]["qos"] == 1
    assert events[0]["payload"]["topic"] == "ward/bed/B12/score/M6"
    calls = []

    class RecordingMqtt:
        async def publish(
            self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False
        ) -> None:
            calls.append((topic, payload, qos, retain))

    worker = MqttOutboxWorker(store, RecordingMqtt())
    await worker._deliver(events[0])
    assert calls[0][2:] == (1, False)
    assert not any(
        event["delivery_key"] == events[0]["delivery_key"]
        for event in await store.due_mqtt_outbox()
    )


def test_m6_requires_explicit_context_and_research_deployment_profile() -> None:
    with pytest.raises(ValueError, match="context"):
        Settings(m6_enabled=True)
    with pytest.raises(ValueError, match="research-only"):
        Settings(environment="design-real", m6_enabled=True, m6_contexts_file="contexts.json")
