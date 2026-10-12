from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest

from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.api import create_app
from sentinelward.contracts import DemoControlMessage, RequestMessage, Verdict, VerdictMessage
from sentinelward.engine import AutomationEngine
from sentinelward.health import HealthRegistry
from sentinelward.m6_demo import synthetic_frame
from sentinelward.persistence import InMemoryStore
from sentinelward.phase4 import Phase4Coordinator
from sentinelward.phase4_adapters import EvidenceFiles
from sentinelward.phase4_backend import LocalProjection
from sentinelward.phase4_state import (
    Authorization,
    ContainmentPolicy,
    Device,
    MemoryAgentRepository,
)


@dataclass
class BrokerDouble:
    states: dict[str, bool] = field(default_factory=dict)
    disables: list[str] = field(default_factory=list)
    cleans: list[str] = field(default_factory=list)
    enables: list[str] = field(default_factory=list)
    fail: bool = False
    lose_reply: bool = False

    async def disabled(self, device: Device) -> bool:
        return self.states.get(device.device_id, False)

    async def disable(self, device: Device) -> None:
        if self.fail:
            raise RuntimeError("unavailable")
        self.states[device.device_id] = True
        self.disables.append(device.device_id)
        if self.lose_reply:
            self.lose_reply = False
            raise TimeoutError("lost reply after effect")

    async def clean_session(self, device: Device) -> None:
        self.cleans.append(device.device_id)

    async def enable(self, device: Device) -> None:
        self.states[device.device_id] = False
        self.enables.append(device.device_id)


def control(cmd: str, run_id: str, ts: int) -> DemoControlMessage:
    return DemoControlMessage(v=1, type="demo_control", ts=ts, cmd=cmd, run_id=run_id)


def make_lab(
    tmp_path: Path, *, policy: bool = True
) -> tuple[Phase4Coordinator, BrokerDouble, list[int], InMemoryStore]:
    now = [1_000_000]
    store = InMemoryStore()
    repository = MemoryAgentRepository(store)
    backend = LocalProjection(repository)
    broker = BrokerDouble()
    devices = {
        f"MON-{i:02}": Device(
            device_id=f"MON-{i:02}",
            bed_id=f"B{i:02}",
            username=f"MON-{i:02}",
            client_id=f"MON-{i:02}",
            model="same" if i < 3 else "other",
            firmware="v1",
            lab_owned=True,
        )
        for i in range(1, 4)
    }
    agent = Phase4Coordinator(
        repository,
        devices,
        broker,
        backend,
        backend,
        EvidenceFiles(tmp_path),
        ContainmentPolicy(version="fixture", threshold=0.8) if policy else None,
        True,
        clock_ms=lambda: now[0],
    )
    return agent, broker, now, store


def verdict(
    now: list[int], value: Verdict, *, bed: str = "B01", confidence: float = 0.9
) -> VerdictMessage:
    priorities = {
        Verdict.NORMAL: "none",
        Verdict.EMERGENCY: "high",
        Verdict.BOTH: "high",
        Verdict.LOOSE_SENSOR: "low",
        Verdict.DEVICE_ATTACK: "none",
    }
    return VerdictMessage(
        v=1,
        type="verdict",
        bed_id=bed,
        ts=now[0],
        window_start=now[0],
        verdict=value,
        priority=priorities.get(value, "medium"),
        confidence=confidence,
        trust=0.2,
        last_trusted_ts=now[0] - 5000,
        reasons=["Test fixture"],
        scores={},
    )


def authorization(
    now: list[int], request_id: str, target: str, action: str, role: str = "it"
) -> Authorization:
    return Authorization(
        request_id=request_id,
        by="staff:operator",
        role=role,
        action=action,
        target_id=target,
        run_id="runA",
        expires_ts=now[0] + 10_000,
    )


@pytest.mark.asyncio
async def test_containment_concurrency_evidence_watch_and_undo(tmp_path: Path) -> None:
    agent, broker, now, store = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    frame = synthetic_frame(0, bed_id="B01").model_copy(update={"ts": now[0], "nibp": None})
    await agent.observe(frame)
    now[0] += 5000
    message = verdict(now, Verdict.BOTH)
    await asyncio.gather(*(agent.handle_verdict(message) for _ in range(4)))
    assert broker.disables == ["MON-01"]
    assert broker.cleans == ["MON-01"]
    state = await agent.snapshot()
    assert state["bed_projections"]["B01"]["state"] == "untrusted"
    assert state["bed_projections"]["B01"]["latest"]["hr"] == frame.hr
    assert state["effective_watches"]["MON-02"]
    assert state["effective_watches"].get("MON-03", []) == []
    [incident] = state["incidents"].values()
    assert agent.evidence.verify(incident["evidence"])
    Path(incident["evidence"][0]["path"]).write_text("corrupt", encoding="utf-8")
    assert not agent.evidence.verify(incident["evidence"])
    original = next(effect for effect in state["effects"].values() if effect.get("reversible"))
    request = RequestMessage(
        v=1,
        type="request",
        request_id="req1",
        ts=now[0],
        by="staff:operator",
        action="undo_action",
        target_id=original["action_id"],
    )
    with pytest.raises(PermissionError):
        await agent.handle_request(request)
    await agent.register_authorization(
        authorization(now, "req1", original["action_id"], "undo_action")
    )
    await agent.handle_request(request)
    await agent.handle_request(request)
    assert broker.enables == ["MON-01"]
    state = await agent.snapshot()
    assert len(state["undo_links"]) == 1
    assert state["bed_projections"]["B01"]["state"] == "reconnecting"
    undos = [
        event["payload"]["body"]
        for event in store.outbox.values()
        if event["payload"]["body"].get("undoes") and event["payload"]["body"]["result"] == "ok"
    ]
    assert undos[0]["approved_by"] == "staff:operator"


@pytest.mark.asyncio
async def test_unknown_effect_reconciles_after_restart_without_second_disable(
    tmp_path: Path,
) -> None:
    agent, broker, now, _ = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    broker.lose_reply = True
    message = verdict(now, Verdict.TAMPERING)
    await agent.handle_verdict(message)
    state = await agent.snapshot()
    assert any(e["status"] == "unknown" for e in state["effects"].values())
    restarted = Phase4Coordinator(
        agent.repository,
        agent.inventory,
        broker,
        agent.projection,
        agent.watch,
        agent.evidence,
        agent.policy,
        True,
        clock_ms=lambda: now[0],
    )
    await restarted.handle_verdict(message)
    assert broker.disables == ["MON-01"]
    assert broker.cleans == ["MON-01"]


@pytest.mark.asyncio
async def test_engine_preserves_a1_when_containment_fails(tmp_path: Path) -> None:
    agent, broker, now, store = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    broker.fail = True
    alerts = SimulatedActionPort()
    engine = AutomationEngine(store=store, action_port=alerts, phase4=agent)
    await engine.run(verdict(now, Verdict.BOTH), thread_id="both")
    assert [(r.agent_id, r.source_verdict.priority) for r in alerts.calls] == [("A1", "high")]
    assert any(e["status"] == "failed" for e in (await agent.snapshot())["effects"].values())


@pytest.mark.asyncio
@pytest.mark.parametrize("confidence,expected", [(0.79, 0), (0.8, 1), (0.81, 1)])
async def test_explicit_fixture_threshold(tmp_path: Path, confidence: float, expected: int) -> None:
    agent, broker, now, _ = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.TAMPERING, confidence=confidence))
    assert len(broker.disables) == expected


@pytest.mark.asyncio
async def test_missing_policy_and_network_only_do_not_isolate(tmp_path: Path) -> None:
    agent, broker, now, _ = make_lab(tmp_path, policy=False)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.TAMPERING))
    now[0] += 5000
    await agent.handle_verdict(verdict(now, Verdict.DEVICE_ATTACK))
    assert broker.disables == []


@pytest.mark.asyncio
async def test_ticket_distinct_loose_episodes_merge_drift_and_human_closure(tmp_path: Path) -> None:
    agent, _, now, _ = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    for _ in range(5):
        await agent.handle_verdict(verdict(now, Verdict.LOOSE_SENSOR))
        now[0] += 5000
    assert not (await agent.snapshot())["tickets"]
    for _ in range(2):
        await agent.handle_verdict(verdict(now, Verdict.NORMAL))
        now[0] += 5000
        await agent.handle_verdict(verdict(now, Verdict.LOOSE_SENSOR))
        now[0] += 5000
    [(ticket_id, ticket)] = (await agent.snapshot())["tickets"].items()
    assert ticket["loose_episodes_30m"] == 3
    await agent.handle_verdict(verdict(now, Verdict.DRIFTING))
    state = await agent.snapshot()
    assert len(state["tickets"]) == 1
    assert set(state["tickets"][ticket_id]["fault_types"]) == {"DRIFTING", "LOOSE_SENSOR"}
    ticket = state["tickets"][ticket_id]
    auth = authorization(now, "close1", ticket_id, "ticket_status", "biomed")
    await agent.set_ticket_status(
        ticket_id,
        authorization=auth,
        status="done",
        expected_revision=ticket["revision"],
        note="Human repair confirmed",
    )
    now[0] += 5000
    await agent.handle_verdict(verdict(now, Verdict.DRIFTING))
    assert len((await agent.snapshot())["tickets"]) == 1
    now[0] += 5000
    await agent.handle_verdict(verdict(now, Verdict.NORMAL))
    now[0] += 5000
    await agent.handle_verdict(verdict(now, Verdict.DRIFTING))
    assert len((await agent.snapshot())["tickets"]) == 2
    auth = authorization(now, "close1", ticket_id, "ticket_status", "biomed")
    with pytest.raises(ValueError, match="revision"):
        await agent.set_ticket_status(
            ticket_id,
            authorization=auth,
            status="new",
            expected_revision=ticket["revision"],
            note="stale",
        )


@pytest.mark.asyncio
async def test_reset_history_lab_restoration_and_stale_observations(tmp_path: Path) -> None:
    agent, broker, now, store = make_lab(tmp_path)
    calls: list[int] = []

    async def reset_alerts(start: int, beds: list[str]) -> None:
        calls.append(start)

    agent.reset_alerts = reset_alerts
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.BOTH))
    prior = verdict(now, Verdict.DRIFTING)
    now[0] += 5000
    await agent.handle_verdict(verdict(now, Verdict.DRIFTING))
    history = len(store.audits)
    now[0] += 5000
    reset = control("reset", "runA", now[0])
    await agent.handle_control(reset)
    await agent.handle_control(reset)
    assert broker.states["MON-01"]
    assert (await agent.snapshot())["tickets"]
    assert len(store.audits) > history
    now[0] += 5000
    await agent.handle_control(control("run", "runB", now[0]))
    assert broker.enables == ["MON-01"]
    with pytest.raises(ValueError, match="stale"):
        await agent.handle_verdict(prior)
    state = await agent.snapshot()
    assert state["loose_active"] == state["drift_active"] == []
    assert state["authorizations"] == {}
    assert calls


@pytest.mark.asyncio
async def test_authenticated_internal_api_and_stale_ticket_revision(tmp_path: Path) -> None:
    agent, _, now, _ = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.DRIFTING))
    app = create_app(HealthRegistry(), phase4=agent, service_token="test-only")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://lab"
    ) as client:
        assert (await client.get("/internal/v1/phase4/status")).status_code == 401
        assert (
            await client.get(
                "/internal/v1/phase4/status", headers={"Authorization": "Bearer test-only"}
            )
        ).status_code == 200
        [(ticket_id, ticket)] = (await agent.snapshot())["tickets"].items()
        body = {
            "authorization": authorization(
                now, "c1", ticket_id, "ticket_status", "nurse"
            ).model_dump(mode="json"),
            "status": "done",
            "expected_revision": ticket["revision"],
        }
        result = await client.post(
            f"/internal/v1/phase4/tickets/{ticket_id}/status",
            json=body,
            headers={"Authorization": "Bearer test-only"},
        )
        assert result.status_code == 403


@pytest.mark.asyncio
async def test_watch_expiry_and_source_silence(tmp_path: Path) -> None:
    agent, _, now, store = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.TAMPERING))
    count = len(store.outbox)
    now[0] += 330_000
    with pytest.raises(ValueError, match="offline"):
        await agent.handle_verdict(verdict(now, Verdict.BOTH, bed="B03"))
    assert len(store.outbox) == count
    now[0] += 3_600_000
    await agent.advance()
    assert (await agent.snapshot())["effective_watches"]["MON-02"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("value", list(Verdict))
async def test_all_eight_verdicts_have_declared_non_a1_effects(
    tmp_path: Path, value: Verdict
) -> None:
    agent, broker, now, _ = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, value))
    state = await agent.snapshot()
    assert bool(broker.disables) == (value in {Verdict.TAMPERING, Verdict.BOTH})
    assert bool(state["incidents"]) == (
        value in {Verdict.TAMPERING, Verdict.BOTH, Verdict.DEVICE_ATTACK}
    )
    assert bool(state["tickets"]) == (value == Verdict.DRIFTING)


@pytest.mark.asyncio
async def test_ticket_undo_is_compensation_and_preserves_audit(tmp_path: Path) -> None:
    agent, _, now, store = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.DRIFTING))
    state = await agent.snapshot()
    original = next(e for e in state["effects"].values() if e["agent"] == "A6")
    await agent.register_authorization(
        authorization(now, "undo-ticket", original["action_id"], "undo_action")
    )
    request = RequestMessage(
        v=1,
        type="request",
        request_id="undo-ticket",
        ts=now[0],
        by="staff:operator",
        action="undo_action",
        target_id=original["action_id"],
    )
    await agent.handle_request(request)
    await agent.handle_request(request)
    [ticket] = (await agent.snapshot())["tickets"].values()
    assert ticket["status"] == "done" and ticket["resolution"] == "cancelled_by_undo"
    assert len((await agent.snapshot())["undo_links"]) == 1
    assert store.audits


@pytest.mark.asyncio
async def test_watch_undo_only_revokes_owned_watch_change(tmp_path: Path) -> None:
    agent, _, now, _ = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.BOTH))
    original = next(
        e
        for e in (await agent.snapshot())["effects"].values()
        if e["agent"] == "A4" and e.get("reversible")
    )
    await agent.register_authorization(
        authorization(now, "undo-watch", original["action_id"], "undo_action")
    )
    await agent.handle_request(
        RequestMessage(
            v=1,
            type="request",
            request_id="undo-watch",
            ts=now[0],
            by="staff:operator",
            action="undo_action",
            target_id=original["action_id"],
        )
    )
    assert (await agent.snapshot())["effective_watches"]["MON-02"] == []


@pytest.mark.asyncio
async def test_backend_reference_rejects_old_revisions_and_checks_human_role(
    tmp_path: Path,
) -> None:
    from sentinelward.contracts import RecordMessage
    from sentinelward.phase4_reference import RecordProjection, create_reference_backend

    records = RecordProjection()
    record = RecordMessage(
        v=1,
        type="record",
        ts=1_000_000,
        kind="ticket",
        record_id="tk1",
        by="A6",
        data={"run_id": "runA", "revision": 2, "status": "done"},
    )
    assert await records.consume(record, "runA")
    assert not await records.consume(
        record.model_copy(update={"data": {"run_id": "runA", "revision": 1}}), "runA"
    )
    assert not await records.consume(record, "runB")
    assert records.records["tk1"].data["status"] == "done"
    agent, _, now, _ = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.DRIFTING))
    [(ticket_id, ticket)] = (await agent.snapshot())["tickets"].items()
    app = create_reference_backend(
        agent,
        service_token="test-service",
        staff_tokens={
            "test-biomed": ("staff:biomed", "biomed"),
            "test-nurse": ("staff:priya", "nurse"),
        },
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://lab"
    ) as client:
        body = {
            "status": "done",
            "expected_revision": ticket["revision"],
            "note": "repaired by person",
        }
        assert (
            await client.patch(
                f"/api/tickets/{ticket_id}",
                json=body,
                headers={"Authorization": "Bearer test-nurse"},
            )
        ).status_code == 403
        result = await client.patch(
            f"/api/tickets/{ticket_id}", json=body, headers={"Authorization": "Bearer test-biomed"}
        )
        assert result.status_code == 200 and result.json()["reference_only"]
        assert (
            await client.patch(
                f"/api/tickets/{ticket_id}",
                json=body,
                headers={"Authorization": "Bearer test-biomed"},
            )
        ).status_code == 409


@pytest.mark.asyncio
async def test_run_expiry_projects_offline_without_new_model_or_ticket(tmp_path: Path) -> None:
    agent, _, now, store = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.observe(
        synthetic_frame(0, bed_id="B03").model_copy(update={"ts": now[0], "nibp": None})
    )
    before = len(store.outbox)
    now[0] += 330_000
    await agent.advance()
    bed = (await agent.snapshot())["bed_projections"]["B03"]
    assert bed["state"] == "offline" and bed["offline_since"] == 1_330_000 and bed["latest"]["hr"]
    assert len(store.outbox) == before


@pytest.mark.asyncio
async def test_reset_waits_for_old_workflow_and_prevents_cross_run_state(tmp_path: Path) -> None:
    from sentinelward.contracts import ActionRequest, ActionResult

    agent, _, now, store = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    started, release = asyncio.Event(), asyncio.Event()

    class SlowAlert:
        async def execute(self, request: ActionRequest, *, action_id: str) -> ActionResult:
            started.set()
            await release.wait()
            return ActionResult(
                action_id=action_id,
                idempotency_key=request.idempotency_key,
                status="completed",
                detail="test alert reserved",
            )

    engine = AutomationEngine(store=store, action_port=SlowAlert(), phase4=agent)
    running = asyncio.create_task(engine.run(verdict(now, Verdict.BOTH), thread_id="old-run"))
    await started.wait()
    resetting = asyncio.create_task(agent.handle_control(control("reset", "runA", now[0] + 5000)))
    await asyncio.sleep(0)
    assert not resetting.done()
    release.set()
    await running
    await resetting
    assert not (await agent.snapshot())["active"]
    now[0] += 10_000
    await agent.handle_control(control("run", "runB", now[0]))
    state = await agent.snapshot()
    assert not state["untrusted"] and not state["buffers"]
    assert all(e["run_id"] != "runB" for e in state["effects"].values())


@pytest.mark.asyncio
async def test_old_containment_undo_cannot_enable_a_newly_isolated_device(tmp_path: Path) -> None:
    agent, broker, now, _ = make_lab(tmp_path)
    await agent.handle_control(control("run", "runA", now[0]))
    await agent.handle_verdict(verdict(now, Verdict.TAMPERING))
    original = next(
        e
        for e in (await agent.snapshot())["effects"].values()
        if e.get("reversible") and e["agent"] == "A2"
    )
    now[0] += 5000
    await agent.handle_verdict(verdict(now, Verdict.NORMAL))
    now[0] += 5000
    await agent.handle_verdict(verdict(now, Verdict.TAMPERING))
    await agent.register_authorization(
        authorization(now, "old-undo", original["action_id"], "undo_action")
    )
    with pytest.raises(ValueError, match="newer containment"):
        await agent.handle_request(
            RequestMessage(
                v=1,
                type="request",
                request_id="old-undo",
                ts=now[0],
                by="staff:operator",
                action="undo_action",
                target_id=original["action_id"],
            )
        )
    assert broker.states["MON-01"] and not broker.enables
