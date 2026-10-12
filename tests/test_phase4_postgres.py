from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from sentinelward.contracts import Verdict
from sentinelward.phase4 import Phase4Coordinator
from sentinelward.phase4_adapters import EvidenceFiles, MosquittoBrokerControl
from sentinelward.phase4_backend import LocalProjection
from sentinelward.phase4_factory import Phase4Configuration
from sentinelward.phase4_state import PostgresAgentRepository
from tests.test_phase4 import control, verdict

DATABASE = os.getenv("SENTINEL_TEST_DATABASE_URL")
CONFIG = os.getenv("SENTINEL_TEST_PHASE4_CONFIG")


@pytest.mark.integration
@pytest.mark.skipif(DATABASE is None, reason="isolated PostgreSQL required")
@pytest.mark.asyncio
async def test_phase4_restart_keeps_ticket_state_and_audit(tmp_path: Path) -> None:
    assert DATABASE is not None
    repository = PostgresAgentRepository(DATABASE)
    backend = LocalProjection(repository)
    from tests.test_phase4 import make_lab

    template, broker, now, _ = make_lab(tmp_path)
    async with repository.transaction() as unit:
        now[0] = max(unit.state.control_ts, *unit.state.highwater.values(), 1_000_000) + 20_000
    run_id = "pg_" + uuid4().hex
    agent = Phase4Coordinator(
        repository,
        template.inventory,
        broker,
        backend,
        backend,
        template.evidence,
        template.policy,
        True,
        clock_ms=lambda: now[0],
    )
    await agent.handle_control(control("run", run_id, now[0]))
    await agent.handle_verdict(verdict(now, Verdict.DRIFTING))
    first = await agent.snapshot()
    [(ticket_id, ticket)] = [(k, v) for k, v in first["tickets"].items() if v["run_id"] == run_id]
    restarted = Phase4Coordinator(
        repository,
        template.inventory,
        broker,
        backend,
        backend,
        template.evidence,
        template.policy,
        True,
        clock_ms=lambda: now[0],
    )
    await restarted.handle_verdict(verdict(now, Verdict.DRIFTING))
    assert (await restarted.snapshot())["tickets"][ticket_id] == ticket
    now[0] += 5000
    await restarted.handle_control(control("reset", run_id, now[0]))
    snapshot = await restarted.snapshot()
    assert snapshot["active"] is False
    assert snapshot["tickets"][ticket_id] == ticket
    async with await psycopg.AsyncConnection.connect(DATABASE) as connection:
        cursor = await connection.execute(
            "SELECT count(*) FROM automation.audit_events WHERE correlation_id=%s",
            (f"phase4:{run_id}",),
        )
        assert (await cursor.fetchone())[0] >= 3


@pytest.mark.integration
@pytest.mark.skipif(
    DATABASE is None or CONFIG is None, reason="real isolated broker and PostgreSQL required"
)
@pytest.mark.asyncio
async def test_real_broker_postgres_effects_survive_restart(tmp_path: Path) -> None:
    assert DATABASE is not None and CONFIG is not None
    configuration = Phase4Configuration.model_validate(json.loads(Path(CONFIG).read_text()))
    repository = PostgresAgentRepository(DATABASE)
    backend = LocalProjection(repository)
    broker = MosquittoBrokerControl(configuration.broker)
    now = [2_000_000]
    async with repository.transaction() as unit:
        now[0] = max(unit.state.control_ts, *unit.state.highwater.values(), now[0]) + 20_000
    run_id = "broker_" + uuid4().hex
    agent = Phase4Coordinator(
        repository,
        {d.device_id: d for d in configuration.inventory},
        broker,
        backend,
        backend,
        EvidenceFiles(tmp_path),
        configuration.containment_policy,
        True,
        clock_ms=lambda: now[0],
    )
    await agent.handle_control(control("run", run_id, now[0]))
    await agent.handle_verdict(verdict(now, Verdict.BOTH))
    assert await broker.disabled(configuration.inventory[0])
    first = await agent.snapshot()
    restarted = Phase4Coordinator(
        repository,
        agent.inventory,
        broker,
        backend,
        backend,
        agent.evidence,
        agent.policy,
        True,
        clock_ms=lambda: now[0],
    )
    await restarted.handle_verdict(verdict(now, Verdict.BOTH))
    second = await restarted.snapshot()
    assert len(second["incidents"]) == len(first["incidents"])
    assert len(second["watches"]) == len(first["watches"])
    now[0] += 5000
    await restarted.handle_control(control("reset", run_id, now[0]))
    assert await broker.disabled(configuration.inventory[0])
    now[0] += 5000
    await restarted.handle_control(control("run", "new_" + uuid4().hex, now[0]))
    assert not await broker.disabled(configuration.inventory[0])
