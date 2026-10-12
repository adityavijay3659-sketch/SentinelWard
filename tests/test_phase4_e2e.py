"""Isolated real MQTT + PostgreSQL + frozen M6 + actual A1 screen workflow."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import paho.mqtt.client as mqtt
import pytest
from paho.mqtt.enums import CallbackAPIVersion

from sentinelward.adapters.alert_publisher import MqttAlertPublisher, MqttOutboxWorker
from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.alert_persistence import PostgresAlertStore
from sentinelward.alerts import AlertCoordinator
from sentinelward.config import Settings
from sentinelward.contracts import Verdict, parse_wire_message
from sentinelward.demo_lifecycle import DemoM6Handler, PostgresDemoRepository
from sentinelward.engine import AutomationEngine
from sentinelward.health import HealthRegistry
from sentinelward.m6 import EpisodeContext
from sentinelward.persistence import PostgresStore
from sentinelward.phase2_actions import Phase2ActionPort
from sentinelward.phase4_backend import LocalClinicalReference
from sentinelward.phase4_factory import Phase4Configuration, build_phase4
from sentinelward.presentation import wire_output_views
from sentinelward.service import MessageService
from tests.test_alerts import FakeScheduler
from tests.test_demo_lifecycle import _frame
from tests.test_phase4 import control, verdict

DATABASE = os.getenv("SENTINEL_TEST_DATABASE_URL")
CONFIG = os.getenv("SENTINEL_TEST_PHASE4_CONFIG")


class ActualBus:
    def __init__(self, config: Phase4Configuration, credentials: dict[str, str]) -> None:
        self.clients: dict[str, mqtt.Client] = {}
        self.messages: queue.Queue[tuple[str, bytes]] = queue.Queue()
        for actor in ("p4-observer", "p4-backend", "p4-decision", "MON-01"):
            client = mqtt.Client(
                CallbackAPIVersion.VERSION2,
                client_id=actor if actor.startswith("MON-") else actor + uuid4().hex[:8],
            )
            client.username_pw_set(actor, credentials[actor])
            ready = threading.Event()

            def connected(
                c: mqtt.Client,
                u: Any,
                f: Any,
                reason: Any,
                props: Any,
                receipt: threading.Event = ready,
            ) -> None:
                if not reason.is_failure:
                    receipt.set()

            client.on_connect = connected
            client.connect(config.broker.host, config.broker.port)
            client.loop_start()
            if not ready.wait(5):
                raise RuntimeError("isolated MQTT actor could not connect")
            self.clients[actor] = client
        observer = self.clients["p4-observer"]
        subscribed = threading.Event()
        observer.on_subscribe = lambda *args: subscribed.set()
        observer.on_message = lambda c, u, m: self.messages.put((str(m.topic), bytes(m.payload)))
        observer.subscribe("ward/#", qos=1)
        if not subscribed.wait(5):
            raise RuntimeError("observer ACL rejected")

    async def publish(
        self,
        topic: str,
        payload: bytes,
        *,
        qos: int = 1,
        retain: bool = False,
        actor: str = "p4-observer",
    ) -> None:
        delivery = self.clients[actor].publish(topic, payload, qos=qos, retain=retain)
        await asyncio.to_thread(delivery.wait_for_publish, 5)

    async def send_to_service(
        self, service: MessageService, topic: str, body: bytes, actor: str
    ) -> None:
        await self.publish(topic, body, actor=actor)
        for _ in range(100):
            received_topic, received = await asyncio.to_thread(self.messages.get, True, 5)
            if received_topic == topic and received == body:
                await service.handle(received_topic, received)
                return
        raise RuntimeError("real MQTT receipt not found")

    def close(self) -> None:
        for client in self.clients.values():
            client.disconnect()
            client.loop_stop()


@pytest.mark.integration
@pytest.mark.skipif(
    DATABASE is None or CONFIG is None, reason="isolated real broker and PostgreSQL required"
)
@pytest.mark.asyncio
async def test_real_mqtt_demo_cycle_preserves_m6_a1_and_resets(tmp_path: Path) -> None:
    assert DATABASE is not None and CONFIG is not None
    path = Path(CONFIG)
    config = Phase4Configuration.model_validate(json.loads(path.read_text()))
    bus = await asyncio.to_thread(
        ActualBus, config, json.loads((path.parent / "credentials.json").read_text())
    )
    agent = build_phase4(path, DATABASE)
    now = [20_000_000]
    prior = await agent.snapshot()
    now[0] = max(prior["control_ts"], *prior["highwater"].values(), now[0]) + 20_000
    now[0] = ((now[0] + 4999) // 5000) * 5000
    agent.clock_ms = lambda: now[0]
    store = PostgresStore(DATABASE)
    clinical = LocalClinicalReference()
    scheduler = FakeScheduler()
    alert_store = PostgresAlertStore(DATABASE)
    alerts = AlertCoordinator(
        store=alert_store,
        publisher=MqttAlertPublisher(store),
        roster_provider=clinical,
        notifier=clinical,
        waveform_provider=clinical,
        scheduler=scheduler,
        escalation_seconds=30,
        clock=lambda: now[0],
    )
    agent.reset_alerts = alerts.reset_demo
    agent.bind_alert_run = alerts.bind_demo_run
    demo = DemoM6Handler(
        PostgresDemoRepository(DATABASE),
        {"B01": EpisodeContext(episode_id="template", device_id="MON-01", start_ts=0)},
        clock_ms=lambda: now[0],
    )
    engine = AutomationEngine(
        store=store, action_port=Phase2ActionPort(alerts, SimulatedActionPort()), phase4=agent
    )
    service = MessageService(
        Settings(mqtt_tls=False),
        store,
        engine,
        HealthRegistry(),
        demo_handler=demo,
        m6_handler=demo,
        alert_request_handler=alerts,
        phase4=agent,
    )
    run_id = "e2e_" + uuid4().hex
    async with demo.repository.transaction() as unit:
        now[0] = (
            max(
                now[0],
                unit.runtime.frame_highwater,
                unit.runtime.episode_start_highwater,
                unit.runtime.last_control_ts,
            )
            + 20_000
        )
    now[0] = ((now[0] + 4999) // 5000) * 5000
    base = now[0]
    try:
        await bus.send_to_service(
            service,
            "ward/demo/control",
            control("run", run_id, base).model_dump_json().encode(),
            "p4-backend",
        )
        for second in range(10):
            now[0] = base + second * 1000
            await bus.send_to_service(
                service,
                "ward/bed/B01/vitals",
                _frame(base, second, bed_id="B01").model_dump_json().encode(),
                "MON-01",
            )
        scores = [
            e
            for e in await store.due_mqtt_outbox()
            if e["payload"]["body"].get("extra", {}).get("demo_run_id") == run_id
        ]
        assert scores and scores[0]["payload"]["body"]["model_version"] == "m6-research-0.3.4"
        now[0] = base + 15_000
        message = verdict(now, Verdict.BOTH)
        await bus.send_to_service(
            service, "ward/bed/B01/verdict", message.model_dump_json().encode(), "p4-decision"
        )
        alert = await alert_store.get_active_alert("B01")
        assert alert is not None and alert.priority == "high" and alert.active
        assert await agent.broker.disabled(config.inventory[0])
        assert scheduler.scheduled
        # The real outbox publishes canonical messages through the real broker.
        events = await store.due_mqtt_outbox(limit=200)
        for event in events:
            await MqttOutboxWorker(store, bus)._deliver(event)
            body = event["payload"]["body"]
            parsed = parse_wire_message(event["payload"]["topic"], json.dumps(body).encode())
            if event["payload"]["topic"] in {"ward/action", "ward/alert"}:
                await service.handle(event["payload"]["topic"], json.dumps(body).encode())
            views = wire_output_views(parsed)
            assert len(views.user) <= 160 and len(views.team) <= 160
        now[0] += 5000
        await bus.send_to_service(
            service,
            "ward/demo/control",
            control("reset", run_id, now[0]).model_dump_json().encode(),
            "p4-backend",
        )
        retired = await alert_store.get_alert(alert.alert_id)
        assert retired is not None and not retired.active and retired.next_escalation_ts is None
        assert alert.alert_id in scheduler.cancelled
        assert (await demo.snapshot())["active"] is False
        now[0] += 5000
        new_run = "new_" + uuid4().hex
        await bus.send_to_service(
            service,
            "ward/demo/control",
            control("run", new_run, now[0]).model_dump_json().encode(),
            "p4-backend",
        )
        state = await agent.snapshot()
        assert not state["untrusted"] and not state["loose_active"] and not state["buffers"]
        assert not await agent.broker.disabled(config.inventory[0])
        # Actual old MQTT verdict cannot create current-run workflow state.
        before = len(state["effects"])
        await bus.send_to_service(
            service, "ward/bed/B01/verdict", message.model_dump_json().encode(), "p4-decision"
        )
        assert len((await agent.snapshot())["effects"]) == before
        assert await alert_store.get_active_alert("B01") is None
    finally:
        bus.close()
