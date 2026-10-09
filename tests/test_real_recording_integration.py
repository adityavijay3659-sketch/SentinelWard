from __future__ import annotations

import json
import os
from itertools import islice
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from sentinelward.contracts import ScoreMessage, VitalsMessage
from sentinelward.m6 import EpisodeContext
from sentinelward.m6_persistence import PostgresM6Handler
from sentinelward.m6_replay import ReplayManifest, replay_vitaldb
from sentinelward.persistence import PostgresStore
from sentinelward.presentation import wire_output_views

DATABASE = os.getenv("SENTINEL_TEST_DATABASE_URL")
DATA_ROOT = os.getenv("SENTINEL_TEST_VITALDB_ROOT")


@pytest.mark.integration
@pytest.mark.skipif(
    not DATABASE or not DATA_ROOT, reason="isolated database and VitalDB root required"
)
@pytest.mark.asyncio
async def test_actual_recording_v1_postgres_restart_duplicate_outbox_and_all_views() -> None:
    assert DATABASE is not None and DATA_ROOT is not None
    root = Path(DATA_ROOT)
    case = json.loads((root / "selection.json").read_text(encoding="utf-8"))["cases"][0]
    folder = root / f"case-{case['case_id']}"
    manifest = ReplayManifest.model_validate_json((folder / "manifest.json").read_bytes())
    # Case 371's ART numeric track starts at 452 seconds. Test a later real
    # waveform segment, not artificial warmup or a generated pressure trace.
    frames = list(islice(replay_vitaldb(manifest, folder), 600, 630))
    assert len(frames) == 30 and all(frame.abp is not None for frame in frames)
    async with await psycopg.AsyncConnection.connect(DATABASE) as connection:
        cursor = await connection.execute(
            "SELECT state FROM automation.m6_states WHERE bed_id='B11'"
        )
        previous = await cursor.fetchone()
    epoch = (int(previous[0]["last_ts"]) // 5000 + 1) * 5000 if previous else 1_000_000_000
    context = EpisodeContext(
        episode_id=f"real-check-{uuid4().hex}", device_id="MON-11", start_ts=epoch
    )
    handler = PostgresM6Handler(DATABASE, {"B11": context})
    scores = []
    converted = []
    for index, frame in enumerate(frames):
        payload = frame.model_dump(mode="json")
        payload.update(bed_id="B11", device_id="MON-11", seq=index, ts=epoch + index * 1000)
        if payload["nibp"] is not None:
            # Preserve the observed cuff timestamp's offset from this frame.
            payload["nibp"]["ts"] = payload["nibp"]["ts"] - frame.ts + payload["ts"]
        converted.append(VitalsMessage.model_validate(payload))
        if index == 15:
            handler = PostgresM6Handler(DATABASE, {"B11": context})
        score = await handler.handle_m6(converted[-1])
        if score is not None:
            scores.append(score)
    assert len(scores) == 5
    assert await handler.handle_m6(converted[-1]) is None
    events = [
        event
        for event in await PostgresStore(DATABASE).due_mqtt_outbox()
        if event["payload"]["topic"] == "ward/bed/B11/score/M6"
        and event["payload"]["body"]["window_start"] >= epoch
    ]
    assert len(events) == 5
    assert all(event["payload"]["qos"] == 1 for event in events)
    for score in scores:
        views = wire_output_views(score)
        assert "\n" not in views.user and "\n" not in views.team
        assert len(views.user) <= 160 and len(views.team) <= 160
        assert ScoreMessage.model_validate(views.model) == score
        assert score.extra["clinical_validation"] == "pending"
