from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from sentinelward.adapters.alert_publisher import MqttAlertPublisher, MqttOutboxWorker
from sentinelward.alerts import AlertRecord
from sentinelward.contracts import AlertMessage, Verdict
from sentinelward.persistence import InMemoryStore


@dataclass
class FakeMqtt:
    published: list[tuple[str, bytes, int, bool]] = field(default_factory=list)
    delivered: asyncio.Event = field(default_factory=asyncio.Event)

    async def publish(
        self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False
    ) -> None:
        self.published.append((topic, payload, qos, retain))
        self.delivered.set()


@pytest.mark.asyncio
async def test_alert_publication_is_durable_before_mqtt_delivery() -> None:
    store = InMemoryStore()
    publisher = MqttAlertPublisher(store)
    alert = AlertMessage(
        v=1,
        type="alert",
        alert_id="al_1",
        ts=1_000,
        bed_id="B02",
        verdict=Verdict.EMERGENCY,
        priority="high",
        text="Bed 2 — possible heart emergency. Go now.",
        to=["staff:priya"],
        ladder_step=1,
        status="open",
        acked_by=None,
        acked_ts=None,
    )
    await publisher.publish_alert(alert)
    assert len(store.outbox) == 1
    assert next(iter(store.outbox.values()))["status"] == "pending"

    mqtt = FakeMqtt()
    worker = MqttOutboxWorker(store, mqtt, poll_seconds=0.01)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(mqtt.delivered.wait(), timeout=1)
    await worker.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert mqtt.published[0][0] == "ward/alert"
    assert mqtt.published[0][2:] == (1, False)
    assert next(iter(store.outbox.values()))["status"] == "delivered"


@pytest.mark.asyncio
async def test_action_outcome_is_published_on_locked_topic_at_qos_one() -> None:
    store = InMemoryStore()
    publisher = MqttAlertPublisher(store)
    alert = AlertRecord(
        alert_id="al_1",
        bed_id="B02",
        verdict=Verdict.EMERGENCY,
        priority="high",
        text="Bed 2 — possible heart emergency. Go now.",
        reasons=["Heart and pulse signals support a real emergency"],
        recipients=["staff:priya"],
        ladder_step=1,
        status="open",
        created_ts=1_000,
        updated_ts=2_000,
        source_window_start=500,
    )
    await publisher.publish_action(
        alert=alert,
        action="send_message",
        result="failed",
        detail="Phone delivery failed for staff:priya",
    )

    event = next(iter(store.outbox.values()))
    assert event["destination"] == "mqtt:ward/action"
    assert event["payload"]["qos"] == 1
    assert event["payload"]["body"]["result"] == "failed"

    mqtt = FakeMqtt()
    worker = MqttOutboxWorker(store, mqtt, poll_seconds=0.01)
    task = asyncio.create_task(worker.run())
    await asyncio.wait_for(mqtt.delivered.wait(), timeout=1)
    await worker.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mqtt.published[0][0] == "ward/action"
    assert mqtt.published[0][2:] == (1, False)
