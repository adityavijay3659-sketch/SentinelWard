"""Twelve-bed accelerated lifecycle software proof; not the real-time whole-team demo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinelward.contracts import DemoControlMessage, DemoSourceEnd, Verdict
from sentinelward.demo_lifecycle import (
    SOURCE_END_SECONDS,
    SOURCE_JOIN_SECONDS,
    DemoM6Handler,
    InMemoryDemoRepository,
)
from sentinelward.m6 import EpisodeContext
from sentinelward.persistence import InMemoryStore
from sentinelward.presentation import wire_output_views
from tests.test_demo_lifecycle import _frame


def test_scenario_uses_locked_contract_values_and_declared_cadence() -> None:
    scenario = json.loads((Path(__file__).parents[1] / "fixtures/phase6-scenario.json").read_text())
    assert set(scenario["required_verdict_targets"]) == {v.value for v in Verdict}
    assert scenario["source_end_s"] == SOURCE_END_SECONDS
    assert scenario["join_s"] == SOURCE_JOIN_SECONDS
    assert scenario["duration_s"] == 1200
    assert scenario["cadence"] == {
        "vitals_frame_s": 1,
        "samples_per_frame": 125,
        "window_s": 10,
        "evaluation_step_s": 5,
    }


@pytest.mark.asyncio
async def test_twelve_bed_boundary_cycle_has_no_silence_scores_and_clean_second_run() -> None:
    store = InMemoryStore()
    repo = InMemoryDemoRepository(store)
    base = 2_000_000_000
    now = [base]
    contexts = {
        f"B{i:02}": EpisodeContext(episode_id="template", device_id=f"MON-{i:02}", start_ts=0)
        for i in range(1, 13)
    }
    demo = DemoM6Handler(repo, contexts, clock_ms=lambda: now[0])
    await demo.handle_control(
        DemoControlMessage(v=1, type="demo_control", ts=base, cmd="run", run_id="phase6_A")
    )
    first = await demo.snapshot()
    assert all(b["state"] != "live" for b in first["beds"] if b["bed_id"] in {"B04", "B07"})
    # Exercise each bed's first real aligned window and its end boundary without claiming
    # an uninterrupted 20-minute replay or creating a new model experiment.
    old_episodes = {
        key: bed.context.episode_id
        for key, bed in repo.runtime.beds.items()
        if bed.context is not None
    }
    timeline = [
        (second, "frame", bed_id)
        for bed_id in contexts
        for second in range(
            SOURCE_JOIN_SECONDS.get(bed_id, 0), SOURCE_JOIN_SECONDS.get(bed_id, 0) + 10
        )
    ]
    timeline += [(end, "end", bed_id) for bed_id, end in SOURCE_END_SECONDS.items()]
    scores = []
    for second, kind, bed_id in sorted(timeline):
        now[0] = base + second * 1000
        if kind == "frame":
            result = await demo.handle_m6(_frame(base, second, bed_id=bed_id))
            if result is not None:
                scores.append(result)
                assert result.extra["demo_run_id"] == "phase6_A"
                views = wire_output_views(result)
                assert len(views.user) <= 160 and len(views.team) <= 160
            continue
        before = len(store.outbox)
        event = DemoSourceEnd(
            v=1,
            type="demo_source_end",
            run_id="phase6_A",
            ts=now[0],
            bed_id=bed_id,
            device_id=f"MON-{bed_id[1:]}",
            source="simulator",
            reason="recording_complete",
        )
        await demo.source_end(event)
        await demo.source_end(event)
        await demo.advance(now[0] + 1000)
        snapshot = await demo.snapshot()
        bed = next(b for b in snapshot["beds"] if b["bed_id"] == bed_id)
        assert bed["state"] == "offline"
        assert bed["offline_since"] == base + second * 1000
        assert bed["latest"]["hr"] == 60 and bed["latest_ts"] is not None
        assert len(store.outbox) == before
        with pytest.raises(ValueError):
            await demo.handle_m6(_frame(base, second, bed_id=bed_id))
    assert len(scores) == 12
    audit_count = len(store.audits)
    now[0] = base + 1_201_000
    reset = DemoControlMessage(v=1, type="demo_control", ts=now[0], cmd="reset", run_id="phase6_A")
    await demo.handle_control(reset)
    await demo.handle_control(reset)
    assert not repo.runtime.model_states
    assert len(store.audits) >= audit_count
    now[0] += 10_000
    await demo.handle_control(
        DemoControlMessage(v=1, type="demo_control", ts=now[0], cmd="run", run_id="phase6_B")
    )
    assert not repo.runtime.model_states
    assert all(b.last_seq == -1 for b in repo.runtime.beds.values())
    assert all(
        b.context and b.context.episode_id != old_episodes[key]
        for key, b in repo.runtime.beds.items()
    )
    with pytest.raises(ValueError, match="stale"):
        await demo.handle_m6(_frame(base, 9, bed_id="B01"))
