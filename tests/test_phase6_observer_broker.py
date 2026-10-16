"""Observer exercises a real, explicitly configured private broker; publishes only dummy frames."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from sentinelward.m6_demo import synthetic_frame
from sentinelward.phase4_factory import Phase4Configuration
from tests.test_phase4_e2e import ActualBus
from tools.phase6_observe import observe

CONFIG = os.getenv("SENTINEL_TEST_PHASE4_CONFIG")


@pytest.mark.integration
@pytest.mark.skipif(CONFIG is None, reason="isolated actual broker required")
@pytest.mark.asyncio
async def test_read_only_observer_records_actual_mqtt_without_raw_waveforms(tmp_path, monkeypatch):
    assert CONFIG is not None
    path = Path(CONFIG)
    broker = Phase4Configuration.model_validate_json(path.read_bytes())
    credentials = json.loads((path.parent / "credentials.json").read_text("utf-8"))
    monkeypatch.setenv("PHASE6_OBSERVER_PASSWORD", credentials["p4-observer"])
    config = {
        "v": 1,
        "run_id": "phase6_observer_fixture",
        "duration_s": 2,
        "broker": {
            "host": broker.broker.host,
            "port": broker.broker.port,
            "username": "p4-observer",
            "password_env": "PHASE6_OBSERVER_PASSWORD",
            "tls": False,
            "ca_file": None,
        },
        "probes": [],
        "pids": [],
    }
    bus = await asyncio.to_thread(ActualBus, broker, credentials)
    task = asyncio.create_task(asyncio.to_thread(observe, config, tmp_path))
    try:
        deadline = time.monotonic() + 10
        while not (tmp_path / "wire.jsonl").is_file() and not task.done():
            if time.monotonic() > deadline:
                raise TimeoutError("observer did not subscribe in time")
            await asyncio.sleep(0.02)
        await bus.publish(
            "ward/bed/B01/vitals", synthetic_frame(0).model_dump_json().encode(), actor="MON-01"
        )
        result = await asyncio.wait_for(asyncio.shield(task), 15)
        assert result["status"] == "PASS"
        assert result["dropped_by_observer"] == 0
        rows = [json.loads(line) for line in (tmp_path / "wire.jsonl").read_text().splitlines()]
        assert any(r["topic"] == "ward/bed/B01/vitals" and r["validation"] == "VALID" for r in rows)
        assert all("abp" not in row and "payload" not in row for row in rows)
        assert credentials["p4-observer"] not in (tmp_path / "wire.jsonl").read_text()
    finally:
        if not task.done():
            await asyncio.wait_for(asyncio.shield(task), 25)
        bus.close()
