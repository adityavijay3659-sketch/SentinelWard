from __future__ import annotations

import os
import time
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.config import Settings
from sentinelward.contracts import (
    ActionRequest,
    ActionResult,
    VerdictMessage,
    correlation_id_for,
)
from sentinelward.engine import AutomationEngine
from sentinelward.health import HealthRegistry
from sentinelward.persistence import PostgresStore
from sentinelward.service import MessageService

DATABASE_URL = os.getenv("SENTINEL_TEST_DATABASE_URL")


class InterruptedEngine:
    async def run(self, message: VerdictMessage, *, thread_id: str) -> object:
        del message, thread_id
        raise RuntimeError("controlled interruption before graph completion")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="SENTINEL_TEST_DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_postgres_ingress_is_idempotent(contract_fixture: dict[str, Any]) -> None:
    assert DATABASE_URL is not None
    store = PostgresStore(DATABASE_URL)
    message = VerdictMessage.model_validate(contract_fixture["verdicts"][0])
    payload = message.model_dump_json().encode()
    key = f"integration:{uuid4()}:{correlation_id_for(message)}"
    first = await store.record_ingress(
        topic=f"ward/bed/{message.bed_id}/verdict",
        payload=payload,
        message=message,
        idempotency_key=key,
        correlation_id=correlation_id_for(message),
    )
    second = await store.record_ingress(
        topic=f"ward/bed/{message.bed_id}/verdict",
        payload=payload,
        message=message,
        idempotency_key=key,
        correlation_id=correlation_id_for(message),
    )
    assert first is True
    assert second is False


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="SENTINEL_TEST_DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_postgres_action_audit_and_outbox_are_idempotent() -> None:
    assert DATABASE_URL is not None
    store = PostgresStore(DATABASE_URL)
    correlation_id = f"integration:{uuid4()}"
    request = ActionRequest(
        correlation_id=correlation_id,
        agent_id="A1",
        action="send_message",
        target_id="B01",
        bed_id="B01",
        detail="integration test",
    )
    action_id, first_created = await store.reserve_action(request)
    repeated_id, second_created = await store.reserve_action(request)
    assert first_created is True
    assert second_created is False
    assert repeated_id == action_id

    result = ActionResult(
        action_id=action_id,
        idempotency_key=request.idempotency_key,
        status="completed",
        detail="simulated",
    )
    await store.complete_action(result)
    await store.append_audit(
        correlation_id=correlation_id,
        event_type="action.completed",
        actor="A1",
        detail=result.model_dump(mode="json"),
    )
    first_outbox = await store.enqueue_outbox(
        delivery_key=request.idempotency_key,
        destination="test",
        payload=result.model_dump(mode="json"),
        correlation_id=correlation_id,
    )
    second_outbox = await store.enqueue_outbox(
        delivery_key=request.idempotency_key,
        destination="test",
        payload=result.model_dump(mode="json"),
        correlation_id=correlation_id,
    )
    assert first_outbox is True
    assert second_outbox is False


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="SENTINEL_TEST_DATABASE_URL is not configured")
@pytest.mark.asyncio
async def test_restart_resumes_incomplete_ingress_once(
    contract_fixture: dict[str, Any],
) -> None:
    assert DATABASE_URL is not None
    store = PostgresStore(DATABASE_URL)
    source = VerdictMessage.model_validate(contract_fixture["verdicts"][1])
    now_ms = time.time_ns() // 1_000_000
    message = source.model_copy(update={"ts": now_ms, "window_start": now_ms - 5_000})
    payload = message.model_dump_json().encode()
    topic = f"ward/bed/{message.bed_id}/verdict"
    settings = Settings(database_url=DATABASE_URL, mqtt_tls=False)

    interrupted = MessageService(
        settings,
        store,
        InterruptedEngine(),
        HealthRegistry(),
    )
    with pytest.raises(RuntimeError, match="controlled interruption"):
        await interrupted.handle(topic, payload)

    first_adapter = SimulatedActionPort()
    async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        resumed = MessageService(
            settings,
            store,
            AutomationEngine(store=store, action_port=first_adapter, checkpointer=checkpointer),
            HealthRegistry(),
        )
        assert await resumed.handle(topic, payload) is True
    assert len(first_adapter.calls) == 1

    replay_adapter = SimulatedActionPort()
    async with AsyncPostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
        restarted = MessageService(
            settings,
            store,
            AutomationEngine(store=store, action_port=replay_adapter, checkpointer=checkpointer),
            HealthRegistry(),
        )
        assert await restarted.handle(topic, payload) is True
    assert replay_adapter.calls == []
