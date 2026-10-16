"""Phase 5 failure, compensation and source-boundary invariants."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from sentinelward.contracts import RequestMessage
from sentinelward.phase4_reference import create_reference_backend
from sentinelward.phase5_contracts import (
    CoverageReceipt,
    GenerateBriefing,
    HumanCommand,
    ShiftSchedule,
)
from sentinelward.phase5_facts import covered_ms
from tests.test_phase4 import control
from tests.test_phase5 import (
    FixtureWriter,
    authorize,
    incident_report,
    lab,
    routed_alert,
)


@pytest.mark.asyncio
async def test_expired_grant_and_reused_command_rejected(tmp_path):
    agent, phase4, _alerts, now, _store = await lab(tmp_path)
    args = await authorize(agent, now, "expire", "briefing", "WARD", role="nurse")
    now[0] += 10_001
    with pytest.raises(PermissionError):
        await agent.generate_briefing(GenerateBriefing(**args))
    args = await authorize(agent, now, "duplicate", "briefing", "WARD", role="nurse")
    first = await agent.generate_briefing(GenerateBriefing(**args))
    assert await agent.generate_briefing(GenerateBriefing(**args)) == first
    with pytest.raises(ValueError, match="different content"):
        await agent.generate_briefing(GenerateBriefing(**args, since=now[0]))
    now[0] += 1000
    await phase4.handle_control(control("reset", "runA", now[0]))
    now[0] += 1000
    await phase4.handle_control(control("run", "runB", now[0]))
    with pytest.raises(ValueError, match="stale"):
        await agent.generate_briefing(GenerateBriefing(**args))


@pytest.mark.asyncio
async def test_bounded_queue_and_timeout_keep_templates_and_release_control(tmp_path):
    writer = FixtureWriter(wait=asyncio.Event())
    agent, phase4, _alerts, now, _store = await lab(tmp_path, writer)
    agent.queue_limit = 1
    agent.generation_timeout_s = 0.02
    await incident_report(agent, phase4, now)
    args = await authorize(agent, now, "overflow", "briefing", "WARD", role="nurse")
    queued = await agent.generate_briefing(GenerateBriefing(**args))
    status = await agent.status()
    assert queued["revision"] == status["records"]["briefing"][0]["revision"]
    assert queued["narrative"]["fallback_reason"] == "queue_full"
    assert status["records"]["briefing"][0]["narrative"]["fallback_reason"] == "queue_full"
    assert len(status["jobs"]) == 1
    await agent.process_one_job()
    status = await agent.status()
    assert status["jobs"][0]["state"] == "fallback"
    assert status["jobs"][0]["reason"] == "TimeoutError"
    assert status["records"]["report"][0]["revision"] == 1
    assert not agent.phase4.lifecycle_gate.locked()


@pytest.mark.asyncio
async def test_guarded_urgent_remains_with_missing_roster_and_closure_refreshes(tmp_path):
    agent, _phase4, alerts, now, _store = await lab(tmp_path)
    alert = await routed_alert(agent, alerts, now, "missing_roster")
    now[0] += 1
    alert = alert.model_copy(update={"roster": None, "updated_ts": now[0]})
    await alerts.save_alert(alert)
    await agent.observe_alert(alert.wire())
    assert (await agent.status())["urgent"]
    now[0] += 1
    alert = alert.model_copy(update={"active": False, "updated_ts": now[0]})
    await alerts.save_alert(alert)
    assert not (await agent.status())["urgent"]


@pytest.mark.asyncio
async def test_compensation_is_owner_scoped_idempotent_and_cannot_undo_clock(tmp_path):
    agent, phase4, _alerts, now, store = await lab(tmp_path)
    report = await incident_report(agent, phase4, now)
    async with agent.repository.transaction() as unit:
        actions = dict(unit.list("action"))
    clock = next(k for k, v in actions.items() if v["action"] == "start_clock")
    draft = next(k for k, v in actions.items() if v["action"] == "draft_report")
    assert actions[clock]["message"]["undo_id"] is None
    args = await authorize(agent, now, "no_clock", "undo", clock, revision=1)
    with pytest.raises(ValueError, match="cannot be undone"):
        await agent.undo(clock, HumanCommand(**args))
    args = await authorize(agent, now, "undo", "undo", draft, revision=1)
    first = await agent.undo(draft, HumanCommand(**args))
    assert await agent.undo(draft, HumanCommand(**args)) == first
    updated = (await agent.status())["records"]["report"][0]
    assert updated["status"] == "superseded"
    assert updated["deadline_ts"] == report["deadline_ts"]
    assert all(j["state"] == "retired" for j in (await agent.status())["jobs"])
    assert any(a["event_type"] == "phase5.undo" for a in store.audits)


@pytest.mark.asyncio
async def test_reference_action_api_includes_phase5_actions_not_tickets(tmp_path):
    agent, phase4, _alerts, now, _store = await lab(tmp_path)
    await incident_report(agent, phase4, now)
    app = create_reference_backend(phase4, service_token="test", phase5=agent)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://local"
    ) as client:
        headers = {"Authorization": "Bearer test"}
        response = await client.get("/api/actions", headers=headers)
        assert response.status_code == 200
        assert any(a.get("owner") == "A5" for a in response.json()["actions"])
        response = await client.get("/api/tickets", headers=headers)
        assert all("owner" not in t for t in response.json()["tickets"])


def test_coverage_conflicts_are_unknown_not_double_counted():
    assert covered_ms([(0, 100), (50, 150)], [(20, 80), (60, 90)], 0, 150) == 80


@pytest.mark.asyncio
async def test_mqtt_undo_resolves_generated_revision_under_gate(tmp_path):
    agent, _phase4, _alerts, now, _store = await lab(tmp_path)
    args = await authorize(agent, now, "briefing", "briefing", "WARD", role="nurse")
    await agent.generate_briefing(GenerateBriefing(**args))
    async with agent.repository.transaction() as unit:
        key = unit.list("action")[0][0]
    await authorize(agent, now, "undo_request", "undo", key)
    request = RequestMessage(
        v=1,
        type="request",
        request_id="undo_request",
        ts=now[0],
        by="staff:it",
        action="undo_action",
        target_id=key,
    )
    assert await agent.handle_request(request)
    assert (await agent.status())["records"]["briefing"][0]["status"] == "superseded"


@pytest.mark.asyncio
async def test_valid_but_late_generation_cannot_be_accepted(tmp_path):
    agent, phase4, _alerts, now, _store = await lab(tmp_path)
    await incident_report(agent, phase4, now)

    class LateWriter(FixtureWriter):
        async def compose(self, snapshot):
            result = await super().compose(snapshot)
            now[0] += 121_000
            return result

    agent.writer = LateWriter()
    await agent.process_one_job()
    status = await agent.status()
    assert status["jobs"][0]["state"] == "fallback"
    assert status["jobs"][0]["reason"] == "job_deadline_exceeded"
    assert status["records"]["report"][0]["revision"] == 1


@pytest.mark.asyncio
async def test_known_recording_completion_excluded_from_blind_metric(tmp_path):
    agent, phase4, _alerts, now, _store = await lab(tmp_path)
    now[0] = 1_400_000
    await phase4.advance()
    await agent.ingest_coverage(
        CoverageReceipt(
            receipt_id="b3",
            run_id="runA",
            bed_id="B03",
            start_ts=1_000_000,
            end_ts=1_330_000,
            state="untrusted",
            source="backend",
        )
    )
    args = await authorize(agent, now, "briefing", "briefing", "WARD", role="nurse")
    record = await agent.generate_briefing(GenerateBriefing(**args))
    facts = {f["subject"]: f["value"] for f in record["facts"]}
    assert facts["B03_blind_time"] == 330_000
    assert facts["B03_outside_recording_interval"] == 70_000
    assert facts["B03_unknown_coverage"] == 0


@pytest.mark.asyncio
async def test_shift_boundary_dst_nonexistent_and_repeated_hour(tmp_path):
    agent, _phase4, _alerts, _now, _store = await lab(tmp_path)
    agent.staff = agent.staff.model_copy(
        update={"schedule": ShiftSchedule(timezone="America/New_York", starts=["02:30"])}
    )
    spring = int(datetime(2026, 3, 8, 9, tzinfo=UTC).timestamp() * 1000)
    previous = int(datetime(2026, 3, 7, 7, 30, tzinfo=UTC).timestamp() * 1000)
    assert agent._last_shift_boundary(spring) == previous
    agent.staff = agent.staff.model_copy(
        update={"schedule": ShiftSchedule(timezone="America/New_York", starts=["01:30"])}
    )
    autumn = int(datetime(2026, 11, 1, 8, tzinfo=UTC).timestamp() * 1000)
    first_fold = int(datetime(2026, 11, 1, 5, 30, tzinfo=UTC).timestamp() * 1000)
    assert agent._last_shift_boundary(autumn) == first_fold
