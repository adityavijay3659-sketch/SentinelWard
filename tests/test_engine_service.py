from __future__ import annotations

from typing import Any

import pytest

from sentinelward.adapters.fake_actions import SimulatedActionPort
from sentinelward.config import Settings
from sentinelward.contracts import ActionRequest, VerdictMessage
from sentinelward.engine import AutomationEngine
from sentinelward.health import HealthRegistry
from sentinelward.persistence import InMemoryStore
from sentinelward.service import MessageService


class FailOnceEngine:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, message: VerdictMessage, *, thread_id: str) -> dict[str, str]:
        del message, thread_id
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("controlled workflow failure")
        return {"terminal_status": "completed"}


@pytest.mark.asyncio
async def test_replayed_verdict_has_one_effect(contract_fixture: dict[str, Any]) -> None:
    message = VerdictMessage.model_validate(contract_fixture["verdicts"][1])
    store = InMemoryStore()
    adapter = SimulatedActionPort()
    engine = AutomationEngine(store=store, action_port=adapter)
    health = HealthRegistry()
    service = MessageService(Settings(mqtt_tls=False), store, engine, health)
    payload = message.model_dump_json().encode()
    topic = f"ward/bed/{message.bed_id}/verdict"

    assert await service.handle(topic, payload) is True
    assert await service.handle(topic, payload) is True

    assert len(adapter.calls) == 1
    assert len(store.ingress) == 1
    assert health.counters == {"accepted": 1, "workflow_completed": 1, "duplicate": 1}


@pytest.mark.asyncio
async def test_malformed_input_dead_letters_without_action() -> None:
    store = InMemoryStore()
    adapter = SimulatedActionPort()
    service = MessageService(
        Settings(mqtt_tls=False),
        store,
        AutomationEngine(store=store, action_port=adapter),
        HealthRegistry(),
    )
    assert await service.handle("ward/bed/B01/verdict", b"broken") is True
    assert len(store.dead_letters) == 1
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_unauthorized_action_is_audited_and_not_executed() -> None:
    store = InMemoryStore()
    adapter = SimulatedActionPort()
    engine = AutomationEngine(store=store, action_port=adapter)
    unauthorized = ActionRequest(
        correlation_id="B01:1:EMERGENCY",
        agent_id="A7",
        action="disable_client",
        target_id="MON-01",
    )
    state = {
        "action_requests": [unauthorized.model_dump(mode="json")],
    }
    result = await engine._execute_node(state)
    assert result["terminal_status"] == "rejected"
    assert adapter.calls == []
    assert store.audits[0]["event_type"] == "policy.rejected"


@pytest.mark.asyncio
async def test_accepted_but_incomplete_ingress_resumes_on_redelivery(
    contract_fixture: dict[str, Any],
) -> None:
    message = VerdictMessage.model_validate(contract_fixture["verdicts"][1])
    store = InMemoryStore()
    engine = FailOnceEngine()
    health = HealthRegistry()
    service = MessageService(Settings(mqtt_tls=False), store, engine, health)
    payload = message.model_dump_json().encode()
    topic = f"ward/bed/{message.bed_id}/verdict"

    with pytest.raises(RuntimeError, match="controlled workflow failure"):
        await service.handle(topic, payload)
    assert next(iter(store.ingress.values()))["status"] == "accepted"

    assert await service.handle(topic, payload) is True
    assert await service.handle(topic, payload) is True
    assert engine.calls == 2
    assert next(iter(store.ingress.values()))["status"] == "processed"
    assert health.counters["recovery_resume"] == 1
