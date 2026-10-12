from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx
import pytest
from pydantic import ValidationError

from sentinelward.adapters.alert_publisher import MqttOutboxWorker
from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.adapters.mqtt import MqttAdapter
from sentinelward.adapters.record_publisher import MqttRecordPublisher
from sentinelward.api import create_app
from sentinelward.config import Settings
from sentinelward.contracts import (
    DemoControlMessage,
    DemoSourceEnd,
    RecordMessage,
    RequestMessage,
    VitalsMessage,
    parse_wire_message,
)
from sentinelward.demo_lifecycle import DemoM6Handler, InMemoryDemoRepository
from sentinelward.engine import AutomationEngine
from sentinelward.errors import ContractError
from sentinelward.health import HealthRegistry
from sentinelward.m6 import MODEL_VERSION, EpisodeContext, M6Config
from sentinelward.m6_demo import synthetic_frame
from sentinelward.persistence import InMemoryStore
from sentinelward.service import MessageService


@dataclass
class MutableClock:
    now: int

    def __call__(self) -> int:
        return self.now


@dataclass
class RecordingMqtt:
    published: list[tuple[str, bytes, int, bool]] = field(default_factory=list)

    async def publish(
        self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False
    ) -> None:
        self.published.append((topic, payload, qos, retain))


@dataclass
class RecordingAlertRequests:
    calls: list[tuple[str, str, str, int, str]] = field(default_factory=list)

    async def acknowledge(self, alert_id: str, *, by: str, at_ms: int, event_id: str) -> None:
        self.calls.append(("ack", alert_id, by, at_ms, event_id))

    async def escalate(self, alert_id: str, *, by: str, at_ms: int, event_id: str) -> None:
        self.calls.append(("escalate", alert_id, by, at_ms, event_id))


def _handler(
    *, bed_id: str = "B03", base: int = 10_000_000
) -> tuple[DemoM6Handler, InMemoryDemoRepository, InMemoryStore, MutableClock]:
    store = InMemoryStore()
    repository = InMemoryDemoRepository(store)
    clock = MutableClock(base)
    context = EpisodeContext(
        episode_id="template-only", device_id=f"MON-{bed_id[1:]}", start_ts=0
    )
    return DemoM6Handler(repository, {bed_id: context}, clock_ms=clock), repository, store, clock


def _control(cmd: str, run_id: str, ts: int, *, start_at_s: int = 0) -> DemoControlMessage:
    return DemoControlMessage(
        v=1,
        type="demo_control",
        ts=ts,
        cmd=cmd,
        run_id=run_id,
        start_at_s=start_at_s,
    )


def _frame(base: int, second: int, *, bed_id: str = "B03") -> VitalsMessage:
    original = synthetic_frame(second, bed_id=bed_id)
    body = original.model_dump(mode="json")
    body["ts"] = base + second * 1000
    if body["nibp"] is not None:
        body["nibp"]["ts"] = body["ts"]
    return VitalsMessage.model_validate(body)


def _service(
    store: InMemoryStore,
    *,
    demo: DemoM6Handler | None = None,
    alerts: RecordingAlertRequests | None = None,
) -> MessageService:
    return MessageService(
        Settings(mqtt_tls=False),
        store,
        AutomationEngine(store=store, action_port=SimulatedActionPort()),
        HealthRegistry(),
        m6_handler=demo,
        demo_handler=demo,
        alert_request_handler=alerts,
    )


def test_v11_contracts_reject_unknown_or_malformed_commands() -> None:
    valid = _control("run", "run_1", 1_000).model_dump_json().encode()
    assert isinstance(parse_wire_message("ward/demo/control", valid), DemoControlMessage)

    for replacement in (
        {"v": "1"},
        {"v": True},
        {"cmd": "restart"},
        {"run_id": ""},
        {"start_at_s": 1200},
    ):
        body = json.loads(valid) | replacement
        with pytest.raises(ContractError):
            parse_wire_message("ward/demo/control", json.dumps(body).encode())

    request = RequestMessage(
        v=1,
        type="request",
        request_id="req_1",
        ts=1_000,
        by="staff:priya",
        action="ack_alert",
        target_id="al_1",
        bed_id="B03",
    )
    assert parse_wire_message("ward/request", request.model_dump_json().encode()) == request
    with pytest.raises(ValidationError):
        RequestMessage.model_validate(request.model_dump(exclude={"by"}))

    record = RecordMessage(
        v=1,
        type="record",
        ts=1_000,
        kind="report",
        record_id="rep_1",
        by="A5",
        data={"summary": "bounded"},
    )
    assert parse_wire_message("ward/record", record.model_dump_json().encode()) == record
    with pytest.raises(ValidationError, match="owning agent"):
        RecordMessage.model_validate(record.model_dump() | {"by": "A6"})


@pytest.mark.asyncio
async def test_run_reset_and_second_run_have_clean_m6_state() -> None:
    handler, repository, store, clock = _handler(bed_id="B01")
    await handler.handle_control(_control("run", "run_1", clock.now))
    first_episode = repository.runtime.beds["B01"].context
    assert first_episode is not None

    for second in range(10):
        await handler.handle_m6(_frame(clock.now, second, bed_id="B01"))
    saved = repository.runtime.model_states["B01"]
    assert saved["baseline"]
    assert saved["pressure_guard_reference"]
    saved["ph"] = {"positive": 17.0, "negative": 9.0}
    saved["peers"] = [
        {
            "v": 1,
            "type": "score",
            "bed_id": "B01",
            "model": "M3",
            "model_version": "test",
            "window_start": clock.now,
            "window_s": 10,
            "score": 0.1,
            "label": "normal",
            "reason": "test peer",
            "extra": {},
        }
    ]
    audit_count = len(store.audits)
    config_before = repository.runtime.config
    version_before = repository.runtime.model_version

    reset_ts = clock.now + 20_000
    reset = _control("reset", "run_1", reset_ts)
    await handler.handle_control(reset)
    await handler.handle_control(reset)

    assert repository.runtime.model_states == {}
    assert repository.runtime.beds["B01"].context is None
    assert repository.runtime.beds["B01"].last_seq == -1
    assert repository.runtime.beds["B01"].replay_cursor_s is None
    assert repository.runtime.config == config_before == M6Config()
    assert repository.runtime.model_version == version_before == MODEL_VERSION
    assert len(store.audits) == audit_count + 1
    assert any(event["event_type"] == "demo.run_start" for event in store.audits)

    with pytest.raises(ValueError, match="offline/reset"):
        await handler.handle_m6(_frame(clock.now, 10, bed_id="B01"))

    clock.now = reset_ts + 10_000
    await handler.handle_control(_control("run", "run_2", clock.now))
    second_episode = repository.runtime.beds["B01"].context
    assert second_episode is not None and second_episode.episode_id != first_episode.episode_id
    assert repository.runtime.model_states == {}
    assert repository.runtime.beds["B01"].last_seq == -1
    with pytest.raises(ValueError, match="stale message"):
        await handler.handle_m6(_frame(10_000_000, 9, bed_id="B01"))


@pytest.mark.asyncio
async def test_malformed_or_wrong_identity_control_cannot_reset_active_state() -> None:
    handler, repository, store, clock = _handler()
    service = _service(store, demo=handler)
    run = _control("run", "run_1", clock.now)
    await service.handle("ward/demo/control", run.model_dump_json().encode())
    episode = repository.runtime.beds["B03"].context

    malformed = run.model_dump(mode="json") | {
        "cmd": "restart",
        "ts": clock.now + 1_000,
    }
    await service.handle("ward/demo/control", json.dumps(malformed).encode())
    assert store.dead_letters[-1]["code"] == "SCHEMA_INVALID"
    assert repository.runtime.active is True
    assert repository.runtime.run_id == "run_1"
    assert repository.runtime.beds["B03"].context == episode

    wrong_identity = _control("reset", "run_wrong", clock.now + 2_000)
    await service.handle("ward/demo/control", wrong_identity.model_dump_json().encode())
    assert store.dead_letters[-1]["code"] == "DEMO_CONTROL_REJECTED"
    assert repository.runtime.active is True
    assert repository.runtime.run_id == "run_1"
    assert repository.runtime.beds["B03"].context == episode


@pytest.mark.asyncio
async def test_known_recording_completion_marks_offline_without_scoring_silence() -> None:
    handler, repository, store, clock = _handler()
    await handler.handle_control(_control("run", "run_1", clock.now))
    for second in range(10):
        await handler.handle_m6(_frame(clock.now, second))

    scores_before = len(store.outbox)
    last_values = repository.runtime.beds["B03"].latest.copy()
    clock.now += 330_000
    snapshot = await handler.snapshot()
    bed = snapshot["beds"][0]

    assert bed["state"] == "offline"
    assert bed["offline_since"] == 10_330_000
    assert bed["latest"] == last_values
    assert bed["recording_complete"] is True
    assert len(store.outbox) == scores_before

    clock.now += 60_000
    await handler.advance()
    assert len(store.outbox) == scores_before
    with pytest.raises(ValueError, match="offline/reset"):
        await handler.handle_m6(_frame(10_000_000, 330))


@pytest.mark.asyncio
async def test_explicit_source_end_is_run_scoped_and_idempotent() -> None:
    handler, repository, store, clock = _handler()
    await handler.handle_control(_control("run", "run_1", clock.now))
    await handler.handle_m6(_frame(clock.now, 0))
    event = DemoSourceEnd(
        v=1,
        type="demo_source_end",
        run_id="run_1",
        ts=clock.now + 10_000,
        bed_id="B03",
        device_id="MON-03",
        source="simulator",
        reason="recording_complete",
    )
    await handler.source_end(event)
    await handler.source_end(event)
    assert repository.runtime.beds["B03"].state == "offline"
    assert sum(item["event_type"] == "demo.source_end" for item in store.audits) == 1

    stale = event.model_copy(update={"run_id": "run_old", "ts": event.ts + 1_000})
    with pytest.raises(ValueError, match="different demo cycle"):
        await handler.source_end(stale)


@pytest.mark.asyncio
async def test_source_end_timer_ordering_is_idempotent_and_old_run_safe() -> None:
    early, early_repository, early_store, early_clock = _handler()
    await early.handle_control(_control("run", "run_early", early_clock.now))
    await early.handle_m6(_frame(early_clock.now, 0))
    early_event = DemoSourceEnd(
        v=1,
        type="demo_source_end",
        run_id="run_early",
        ts=early_clock.now + 100_000,
        bed_id="B03",
        device_id="MON-03",
        source="simulator",
        reason="recording_complete",
    )
    await early.source_end(early_event)
    await early.advance(early_clock.now + 330_000)
    assert early_repository.runtime.beds["B03"].offline_since == early_event.ts
    assert sum(item["event_type"] == "demo.source_end" for item in early_store.audits) == 1

    late, late_repository, late_store, late_clock = _handler(base=30_000_000)
    await late.handle_control(_control("run", "run_late", late_clock.now))
    await late.handle_m6(_frame(late_clock.now, 0))
    await late.advance(late_clock.now + 330_000)
    timer_offline_since = late_repository.runtime.beds["B03"].offline_since
    late_event = early_event.model_copy(
        update={"run_id": "run_late", "ts": late_clock.now + 340_000}
    )
    await late.source_end(late_event)
    await late.source_end(late_event)
    assert late_repository.runtime.beds["B03"].offline_since == timer_offline_since
    assert sum(item["event_type"] == "demo.source_end" for item in late_store.audits) == 1

    await late.handle_control(_control("reset", "run_late", late_clock.now + 350_000))
    await late.handle_control(_control("run", "run_new", late_clock.now + 360_000))
    with pytest.raises(ValueError, match="different demo cycle"):
        await late.source_end(late_event.model_copy(update={"ts": late_clock.now + 370_000}))
    assert late_repository.runtime.run_id == "run_new"
    assert late_repository.runtime.beds["B03"].completed is False


@pytest.mark.asyncio
async def test_pending_scores_are_retained_but_cannot_publish_after_reset() -> None:
    handler, _, store, clock = _handler()
    await handler.handle_control(_control("run", "run_1", clock.now))
    for second in range(10):
        await handler.handle_m6(_frame(clock.now, second))
    [fetched] = await store.due_mqtt_outbox()

    await handler.handle_control(_control("reset", "run_1", clock.now + 20_000))
    mqtt = RecordingMqtt()
    await MqttOutboxWorker(store, mqtt)._deliver(fetched)

    assert mqtt.published == []
    assert store.outbox[str(fetched["delivery_key"])]["status"] == "unknown"
    assert len(store.outbox) == 1


@pytest.mark.asyncio
async def test_end_to_end_demo_cycle_publishes_score_then_restarts_cleanly() -> None:
    handler, repository, store, clock = _handler()
    service = _service(store, demo=handler)
    run = _control("run", "run_1", clock.now)
    assert await service.handle("ward/demo/control", run.model_dump_json().encode())

    for second in range(10):
        frame = _frame(clock.now, second)
        assert await service.handle("ward/bed/B03/vitals", frame.model_dump_json().encode())

    [event] = await store.due_mqtt_outbox()
    assert event["payload"]["body"]["model_version"] == MODEL_VERSION
    assert event["payload"]["body"]["extra"]["demo_run_id"] == "run_1"
    assert event["payload"]["body"]["extra"]["demo_only"] is True
    mqtt = RecordingMqtt()
    await MqttOutboxWorker(store, mqtt)._deliver(event)
    assert mqtt.published[0][0] == "ward/bed/B03/score/M6"

    await handler.source_end(
        DemoSourceEnd(
            v=1,
            type="demo_source_end",
            run_id="run_1",
            ts=clock.now + 10_000,
            bed_id="B03",
            device_id="MON-03",
            source="simulator",
            reason="recording_complete",
        )
    )
    output_count = len(store.outbox)
    await handler.advance(clock.now + 100_000)
    assert len(store.outbox) == output_count

    reset = _control("reset", "run_1", clock.now + 20_000)
    await service.handle("ward/demo/control", reset.model_dump_json().encode())
    assert repository.runtime.model_states == {}
    audit_count = len(store.audits)

    clock.now += 40_000
    second = _control("run", "run_2", clock.now)
    await service.handle("ward/demo/control", second.model_dump_json().encode())
    assert repository.runtime.model_states == {}
    assert repository.runtime.beds["B03"].state == "offline"
    assert len(store.audits) == audit_count + 1
    await handler.handle_m6(_frame(clock.now, 0))
    assert repository.runtime.beds["B03"].last_seq == 0


@pytest.mark.asyncio
async def test_request_routing_preserves_actor_and_never_calls_m6() -> None:
    store = InMemoryStore()
    alerts = RecordingAlertRequests()
    service = _service(store, alerts=alerts)
    for index, action in enumerate(("ack_alert", "escalate_alert"), 1):
        request = RequestMessage(
            v=1,
            type="request",
            request_id=f"req_{index}",
            ts=index * 1_000,
            by="staff:priya",
            action=action,
            target_id="al_1",
            bed_id="B03",
        )
        await service.handle("ward/request", request.model_dump_json().encode())
    assert alerts.calls == [
        ("ack", "al_1", "staff:priya", 1_000, "req_1"),
        ("escalate", "al_1", "staff:priya", 2_000, "req_2"),
    ]
    assert not any(entry["topic"].endswith("/vitals") for entry in store.ingress.values())

    other = RequestMessage(
        v=1,
        type="request",
        request_id="req_3",
        ts=3_000,
        by="staff:priya",
        action="isolate_device",
        target_id="MON-03",
        bed_id="B03",
    )
    await service.handle("ward/request", other.model_dump_json().encode())
    assert store.audits[-1]["event_type"] == "request.not_owned"


@pytest.mark.asyncio
async def test_records_use_ward_record_and_are_not_model_scores() -> None:
    store = InMemoryStore()
    publisher = MqttRecordPublisher(store)
    record = RecordMessage(
        v=1,
        type="record",
        ts=1_000,
        kind="ticket",
        record_id="tk_1",
        by="A6",
        data={"status": "open"},
    )
    await publisher.publish_record(record)
    [event] = await store.due_mqtt_outbox()
    assert event["payload"]["topic"] == "ward/record"
    assert event["payload"]["body"]["type"] == "record"
    assert "model" not in event["payload"]["body"]


@pytest.mark.asyncio
async def test_internal_offline_projection_requires_auth_and_preserves_values() -> None:
    handler, _, _, clock = _handler()
    await handler.handle_control(_control("run", "run_1", clock.now))
    await handler.handle_m6(_frame(clock.now, 0))
    app = create_app(HealthRegistry(), demo=handler, service_token="secret")
    transport = httpx.ASGITransport(app=app)
    body = {
        "v": 1,
        "type": "demo_source_end",
        "run_id": "run_1",
        "ts": clock.now + 10_000,
        "bed_id": "B03",
        "device_id": "MON-03",
        "source": "backend",
        "reason": "recording_complete",
    }
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/internal/v1/demo/status")).status_code == 401
        response = await client.post(
            "/internal/v1/demo/source-end",
            json=body,
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 200
    bed = response.json()["beds"][0]
    assert bed["state"] == "offline"
    assert bed["offline_since"] == clock.now + 10_000
    assert bed["latest"]["hr"] == 60


def test_mqtt_subscriptions_keep_requests_separate_from_records() -> None:
    class FakeReason:
        is_failure = False

    class FakeClient:
        def __init__(self) -> None:
            self.subscriptions: list[tuple[str, int]] = []

        def subscribe(self, topics: list[tuple[str, int]]) -> tuple[int, int]:
            self.subscriptions = topics
            return 0, 1

    async def handler(topic: str, payload: bytes) -> bool:
        del topic, payload
        return True

    adapter = MqttAdapter(
        host="localhost",
        port=1883,
        client_id="test",
        handler=handler,
        event_loop=__import__("asyncio").new_event_loop(),
        tls=False,
        m6_enabled=True,
        demo_enabled=True,
    )
    client = FakeClient()
    adapter._on_connect(client, None, None, FakeReason(), None)  # type: ignore[arg-type]
    assert ("ward/demo/control", 1) in client.subscriptions
    assert ("ward/request", 1) in client.subscriptions
    assert ("ward/bed/+/vitals", 0) in client.subscriptions
    assert not any(topic == "ward/record" for topic, _ in client.subscriptions)
    adapter._event_loop.close()

\n