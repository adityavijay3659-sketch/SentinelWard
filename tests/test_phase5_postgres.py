"""Real PostgreSQL/MQTT workflow evidence; Granite acceptance is separate."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from sentinelward.adapters.alert_publisher import MqttAlertPublisher, MqttOutboxWorker
from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.adapters.granite import UnavailableWriter
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
from sentinelward.phase5 import Phase5Coordinator
from sentinelward.phase5_contracts import (
    ConfirmReport,
    GenerateBriefing,
    HumanGrant,
    Principal,
    StaffProfile,
)
from sentinelward.phase5_state import PostgresRepository
from sentinelward.service import MessageService
from tests.test_alerts import FakeScheduler
from tests.test_demo_lifecycle import _frame
from tests.test_phase4 import control, make_lab, verdict
from tests.test_phase4_e2e import ActualBus
from tests.test_phase5 import FixtureWriter

DATABASE = os.getenv("SENTINEL_TEST_DATABASE_URL")
BROKER = os.getenv("SENTINEL_TEST_PHASE4_CONFIG")


def staff() -> StaffProfile:
    return StaffProfile(
        version="postgres-fixture",
        nurses=["staff:priya", "staff:ravi"],
        charge_nurse="staff:charge",
        valid_until=253_402_300_799_999,
    )


@pytest.mark.integration
@pytest.mark.skipif(DATABASE is None, reason="isolated PostgreSQL required")
@pytest.mark.asyncio
async def test_phase5_restart_lease_recovery_and_history_preserved(tmp_path: Path):
    phase4, _broker, now, _store = make_lab(tmp_path)
    assert DATABASE is not None
    repository = PostgresRepository(DATABASE)
    async with repository.transaction() as unit:
        now[0] = max(unit.runtime.control_ts + 1000, int(time.time() * 1000))
    alerts = PostgresAlertStore(DATABASE)
    agent = Phase5Coordinator(
        repository, phase4, alerts, staff(), writer=FixtureWriter(), clock_ms=lambda: now[0]
    )
    phase4.after_control = agent.handle_control
    run = "run_" + uuid4().hex
    await phase4.handle_control(control("run", run, now[0]))
    now[0] += 2000
    await phase4.handle_verdict(verdict(now, Verdict.DEVICE_ATTACK))
    incident = next(iter((await phase4.snapshot())["incidents"]))
    grant = HumanGrant(
        request_id="confirm_" + uuid4().hex,
        principal=Principal(by="staff:it", role="it"),
        run_id=run,
        action="confirm_report",
        target_id=incident,
        expires_ts=now[0] + 10_000,
    )
    await agent.register_grant(grant)
    report = await agent.confirm_report(
        incident,
        ConfirmReport(
            request_id=grant.request_id,
            by=grant.principal.by,
            run_id=run,
            ts=now[0],
            noticed_ts=now[0],
            notice_reason="Reviewed fixture",
        ),
    )
    async with repository.transaction() as unit:
        key, job = unit.list("job")[0]
        job.update(state="running", lease_until=now[0] + 100)
        unit.put("job", key, job)
    restored = Phase5Coordinator(
        PostgresRepository(DATABASE),
        phase4,
        alerts,
        staff(),
        writer=FixtureWriter(),
        clock_ms=lambda: now[0],
    )
    assert not await restored.process_one_job()
    now[0] += 101
    assert await restored.process_one_job()
    updated = (await restored.status())["records"]["report"][0]
    assert updated["record_id"] == report["record_id"] and updated["revision"] == 2
    assert updated["deadline_ts"] == report["deadline_ts"]
    async with repository.transaction() as unit:
        unit.put("coverage_cursor", "reused_bed", {"run_id": run, "marker": "old"})
    now[0] += 1000
    phase4.after_control = restored.handle_control
    await phase4.handle_control(control("reset", run, now[0]))
    now[0] += 1000
    next_run = "next_" + uuid4().hex
    await phase4.handle_control(control("run", next_run, now[0]))
    assert not (await restored.status())["records"]["report"]
    async with repository.transaction() as unit:
        assert unit.get("coverage_cursor", "reused_bed") is None
        unit.put("coverage_cursor", "reused_bed", {"run_id": next_run, "marker": "new"})
    async with repository.transaction() as unit:
        assert unit.get("coverage_cursor", "reused_bed")["marker"] == "new"
    async with await psycopg.AsyncConnection.connect(DATABASE) as db:
        retained = await (
            await db.execute(
                "SELECT count(*) FROM automation.phase5_items WHERE kind='coverage_cursor' "
                "AND item_id='reused_bed' AND run_id IN (%s,%s)",
                (run, next_run),
            )
        ).fetchone()
        assert retained[0] == 2
        count = await (
            await db.execute(
                "SELECT count(*) FROM automation.phase5_items WHERE run_id=%s AND kind='report'",
                (run,),
            )
        ).fetchone()
        assert count[0] == 1
        count = await (
            await db.execute(
                "SELECT count(*) FROM automation.audit_events WHERE correlation_id=%s",
                ("phase5:" + run,),
            )
        ).fetchone()
        assert count[0] > 0


@pytest.mark.integration
@pytest.mark.skipif(
    DATABASE is None or BROKER is None, reason="isolated real MQTT/PostgreSQL required"
)
@pytest.mark.asyncio
async def test_real_bus_phase5_a1_m6_records_reset_and_second_run(tmp_path: Path):
    assert DATABASE is not None and BROKER is not None
    path = Path(BROKER)
    config = Phase4Configuration.model_validate_json(path.read_bytes())
    phase4 = build_phase4(path, DATABASE)
    # A previously interrupted containment fixture may have disabled this lab account.
    for device in config.inventory:
        await phase4.broker.enable(device)
    bus = await asyncio.to_thread(
        ActualBus, config, json.loads((path.parent / "credentials.json").read_text())
    )
    try:
        store = PostgresStore(DATABASE)
        repository = PostgresRepository(DATABASE)
        source = await phase4.snapshot()
        async with repository.transaction() as unit:
            start = max(
                int(time.time() * 1000),
                unit.runtime.control_ts + 1000,
                source["control_ts"] + 1000,
                *source["highwater"].values(),
            )
        demo_repo = PostgresDemoRepository(DATABASE)
        async with demo_repo.transaction() as unit:
            start = max(
                start, unit.runtime.last_control_ts + 1000, unit.runtime.frame_highwater + 1000
            )
        start = ((start + 999) // 1000) * 1000
        now = [start]
        phase4.clock_ms = lambda: now[0]
        alerts = PostgresAlertStore(DATABASE)
        publisher = MqttAlertPublisher(store)
        clinical = LocalClinicalReference()
        ladder = AlertCoordinator(
            store=alerts,
            publisher=publisher,
            roster_provider=clinical,
            notifier=clinical,
            waveform_provider=clinical,
            scheduler=FakeScheduler(),
            escalation_seconds=30,
            clock=lambda: now[0],
        )
        phase4.reset_alerts, phase4.bind_alert_run = ladder.reset_demo, ladder.bind_demo_run
        agent = Phase5Coordinator(
            repository, phase4, alerts, staff(), writer=UnavailableWriter(), clock_ms=lambda: now[0]
        )
        phase4.after_control = agent.handle_control
        publisher.on_alert = agent.observe_alert
        engine = AutomationEngine(
            store=store,
            action_port=Phase2ActionPort(ladder, SimulatedActionPort()),
            phase4=phase4,
            phase5=agent,
        )
        demo = DemoM6Handler(
            demo_repo,
            {"B01": EpisodeContext(episode_id="fixture", device_id="MON-01", start_ts=0)},
            clock_ms=lambda: now[0],
        )
        service = MessageService(
            Settings(),
            store,
            engine,
            HealthRegistry(),
            m6_handler=demo,
            demo_handler=demo,
            alert_request_handler=ladder,
            phase4=phase4,
            phase5=agent,
        )
        run = "p5_" + uuid4().hex
        await bus.send_to_service(
            service,
            "ward/demo/control",
            control("run", run, start).model_dump_json().encode(),
            "p4-backend",
        )
        for i in range(15):
            now[0] = start + i * 1000
            await bus.send_to_service(
                service,
                "ward/bed/B01/vitals",
                _frame(start, i, bed_id="B01").model_dump_json().encode(),
                "MON-01",
            )
        now[0] += 1000
        await bus.send_to_service(
            service,
            "ward/bed/B01/verdict",
            verdict(now, Verdict.BOTH).model_dump_json().encode(),
            "p4-decision",
        )
        assert (await agent.status())["urgent"]
        incident = next(
            v for v in (await phase4.snapshot())["incidents"].values() if v["run_id"] == run
        )
        incident_id = next(
            k
            for k, v in (await phase4.snapshot())["incidents"].items()
            if v is not None and v["run_id"] == run
        )
        grant = HumanGrant(
            request_id="c_" + uuid4().hex,
            principal=Principal(by="staff:it", role="it"),
            run_id=run,
            action="confirm_report",
            target_id=incident_id,
            expires_ts=now[0] + 10_000,
        )
        await agent.register_grant(grant)
        await agent.confirm_report(
            incident_id,
            ConfirmReport(
                request_id=grant.request_id,
                by="staff:it",
                run_id=run,
                ts=now[0],
                noticed_ts=incident["ts"],
                notice_reason="IT reviewed fixture",
            ),
        )
        await agent.advance()
        grant = HumanGrant(
            request_id="b_" + uuid4().hex,
            principal=Principal(by="staff:priya", role="nurse"),
            run_id=run,
            action="briefing",
            target_id="WARD",
            expires_ts=now[0] + 10_000,
        )
        await agent.register_grant(grant)
        await agent.generate_briefing(
            GenerateBriefing(request_id=grant.request_id, by="staff:priya", run_id=run, ts=now[0])
        )
        worker = MqttOutboxWorker(store, bus)
        for _ in range(80):
            due = await store.due_mqtt_outbox(limit=200)
            if not due:
                break
            for event in due:
                await worker._deliver(event)
        collected = []
        while not bus.messages.empty():
            topic, body = bus.messages.get_nowait()
            collected.append(parse_wire_message(topic, body))
        assert {m.kind for m in collected if m.type == "record"} >= {
            "report",
            "briefing",
            "workload",
        }
        assert any(m.type == "score" and m.extra.get("demo_run_id") == run for m in collected)
        now[0] += 1000
        await bus.send_to_service(
            service,
            "ward/demo/control",
            control("reset", run, now[0]).model_dump_json().encode(),
            "p4-backend",
        )
        assert not (await agent.status())["urgent"]
        now[0] += 1000
        await bus.send_to_service(
            service,
            "ward/demo/control",
            control("run", "p5next_" + uuid4().hex, now[0]).model_dump_json().encode(),
            "p4-backend",
        )
        assert not (await agent.status())["records"]["report"]
    finally:
        await asyncio.to_thread(bus.close)
