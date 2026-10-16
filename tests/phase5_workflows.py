"""Actual coordinator fixtures for strict acceptance; only inputs are fictional."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sentinelward.adapters.granite import Writer
from sentinelward.alert_persistence import InMemoryAlertStore
from sentinelward.contracts import DemoControlMessage, Verdict
from sentinelward.phase5 import Phase5Coordinator
from sentinelward.phase5_contracts import (
    REPORT_FIELDS,
    ConfirmReport,
    FactSnapshot,
    GenerateBriefing,
    StaffProfile,
)
from sentinelward.phase5_state import MemoryRepository
from tests.test_phase4 import make_lab, verdict
from tests.test_phase5 import authorize, routed_alert


async def make_workflow(
    path: Path, case: dict[str, Any], writer: Writer, *, scheduled: bool = False
) -> tuple[Phase5Coordinator, str, FactSnapshot]:
    phase4, _broker, now, store = make_lab(path)

    def clock() -> int:
        return time.time_ns() // 1_000_000

    phase4.clock_ms = clock
    sample = phase4.inventory["MON-01"]
    phase4.inventory = {
        f"MON-{i:02}": sample.model_copy(
            update={
                "device_id": f"MON-{i:02}",
                "bed_id": f"B{i:02}",
                "username": f"MON-{i:02}",
                "client_id": f"MON-{i:02}",
            }
        )
        for i in range(1, case["beds"] + 1)
    }
    alerts = InMemoryAlertStore()
    profile = (
        {key: "FICTIONAL profile: human review required" for key in REPORT_FIELDS}
        if case["complete"]
        else {}
    )
    agent = Phase5Coordinator(
        MemoryRepository(store),
        phase4,
        alerts,
        StaffProfile(
            version="strict-fictional-1",
            nurses=["staff:priya", "staff:ravi"],
            charge_nurse="staff:charge",
            valid_until=253_402_300_799_999,
        ),
        report_profile=profile,
        writer=writer,
        clock_ms=clock,
    )
    phase4.after_control = agent.handle_control
    start = (clock() // 1000 - 1) * 1000
    await phase4.handle_control(
        DemoControlMessage(
            v=1,
            type="demo_control",
            cmd="run",
            run_id="runA",
            ts=start,
            start_at_s=1140 if scheduled else 0,
        )
    )
    now[0] = clock()
    if case["urgent"]:
        await routed_alert(agent, alerts, now, "strict_urgent")
    if case["kind"] == "report":
        await phase4.handle_verdict(verdict(now, Verdict.DEVICE_ATTACK))
        incident = next(iter((await phase4.snapshot())["incidents"]))
        now[0] = clock()
        args = await authorize(agent, now, "strict-report", "confirm_report", incident)
        record = await agent.confirm_report(
            incident,
            ConfirmReport(**args, noticed_ts=now[0], notice_reason="Fictional IT-reviewed notice"),
        )
        if case["complete"]:
            assert not record["missing_fields"]
        else:
            assert record["missing_fields"]
        key = record["record_id"]
    elif scheduled:
        await phase4.advance()
        await agent.advance()
        key = (await agent.status())["records"]["briefing"][0]["record_id"]
    else:
        now[0] = clock()
        args = await authorize(agent, now, "strict-briefing", "briefing", "WARD", role="nurse")
        record = await agent.generate_briefing(GenerateBriefing(**args))
        key = record["record_id"]
    async with agent.repository.transaction() as unit:
        row = unit.get(case["kind"], key)
        assert row is not None
        raw = unit.get("snapshot", row["snapshot_id"])
        assert raw is not None
        snapshot = FactSnapshot.model_validate(raw)
    assert len(snapshot.facts) == case["facts"]
    return agent, key, snapshot
