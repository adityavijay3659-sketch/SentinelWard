from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from sentinelward.contracts import (
    DemoControlMessage,
    ScoreMessage,
    VitalsMessage,
    parse_wire_message,
)
from sentinelward.demo_lifecycle import DemoM6Handler, InMemoryDemoRepository
from sentinelward.m6 import EpisodeContext
from sentinelward.m6_demo import synthetic_frame
from sentinelward.persistence import InMemoryStore


@dataclass
class BackendProjectionContractStub:
    """Required backend boundary only; this is not the unavailable real backend."""

    current_run_id: str | None = None
    current_episode_by_bed: dict[str, str] = field(default_factory=dict)
    current_scores: dict[str, ScoreMessage] = field(default_factory=dict)
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def begin_run(self, lifecycle_snapshot: dict[str, Any]) -> None:
        run_id = lifecycle_snapshot.get("run_id")
        assert isinstance(run_id, str)
        self.current_run_id = run_id
        self.current_episode_by_bed = {
            str(bed["bed_id"]): str(bed["episode_id"])
            for bed in lifecycle_snapshot["beds"]
            if bed["episode_id"] is not None
        }
        self.current_scores.clear()

    def consume_m6(self, topic: str, payload: bytes) -> bool:
        message = parse_wire_message(topic, payload)
        assert isinstance(message, ScoreMessage) and message.model == "M6"
        run_id = message.extra.get("demo_run_id")
        episode_id = message.extra.get("episode_id")
        if not isinstance(run_id, str):
            self.rejected.append((message.bed_id, "missing_demo_run_id"))
            return False
        if run_id != self.current_run_id:
            self.rejected.append((message.bed_id, "stale_demo_run_id"))
            return False
        if episode_id != self.current_episode_by_bed.get(message.bed_id):
            self.rejected.append((message.bed_id, "stale_episode_id"))
            return False
        self.current_scores[message.bed_id] = message
        return True


def _frame(base: int, second: int) -> VitalsMessage:
    body = synthetic_frame(second, bed_id="B03").model_dump(mode="json")
    body["ts"] = base + second * 1000
    if body["nibp"] is not None:
        body["nibp"]["ts"] = body["ts"]
    return VitalsMessage.model_validate(body)


def _control(cmd: str, run_id: str, ts: int) -> DemoControlMessage:
    return DemoControlMessage(
        v=1,
        type="demo_control",
        ts=ts,
        cmd=cmd,
        run_id=run_id,
        start_at_s=0,
    )


@pytest.mark.asyncio
async def test_old_run_score_is_recognizable_and_rejected_at_backend_boundary() -> None:
    base_a = 20_000_000
    now = [base_a]
    store = InMemoryStore()
    repository = InMemoryDemoRepository(store)
    handler = DemoM6Handler(
        repository,
        {"B03": EpisodeContext(episode_id="template", device_id="MON-03", start_ts=0)},
        clock_ms=lambda: now[0],
    )
    await handler.handle_control(_control("run", "run_A", base_a))
    for second in range(10):
        await handler.handle_m6(_frame(base_a, second))
    [delayed_a] = await store.due_mqtt_outbox()
    delayed_body = delayed_a["payload"]["body"]
    assert delayed_body["extra"]["demo_run_id"] == "run_A"
    assert delayed_body["extra"]["episode_id"]

    await handler.handle_control(_control("reset", "run_A", base_a + 20_000))
    base_b = base_a + 40_000
    now[0] = base_b
    await handler.handle_control(_control("run", "run_B", base_b))
    backend = BackendProjectionContractStub()
    backend.begin_run(await handler.snapshot())

    topic = str(delayed_a["payload"]["topic"])
    assert backend.consume_m6(topic, json.dumps(delayed_body).encode()) is False
    assert backend.rejected == [("B03", "stale_demo_run_id")]
    assert backend.current_scores == {}
    assert store.outbox[str(delayed_a["delivery_key"])]["status"] == "unknown"

    for second in range(10):
        await handler.handle_m6(_frame(base_b, second))
    [current_b] = await store.due_mqtt_outbox()
    current_body = current_b["payload"]["body"]
    assert current_body["extra"]["demo_run_id"] == "run_B"
    assert backend.consume_m6(
        str(current_b["payload"]["topic"]), json.dumps(current_body).encode()
    )
    assert backend.current_scores["B03"].extra["demo_run_id"] == "run_B"

    missing_identity = json.loads(json.dumps(current_body))
    missing_identity["extra"].pop("demo_run_id")
    assert backend.consume_m6(topic, json.dumps(missing_identity).encode()) is False
    assert backend.rejected[-1] == ("B03", "missing_demo_run_id")

\n