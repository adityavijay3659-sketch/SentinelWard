from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from sentinelward.adapters.clinical_backend import ClinicalBackendClient
from sentinelward.adapters.telegram import (
    TelegramCallbackRouter,
    TelegramIdentityMap,
    TelegramNotifier,
)
from sentinelward.alert_persistence import InMemoryAlertStore
from sentinelward.alerts import AlertRecord, CallbackTarget
from sentinelward.contracts import BedsideCheckMessage, Verdict
from sentinelward.errors import DeliveryError


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def send_message(self, **values: Any) -> SimpleNamespace:
        self.messages.append(values)
        return SimpleNamespace(message_id=7)


@pytest.mark.asyncio
async def test_clinical_backend_validates_live_roster() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.url.path == "/internal/v1/ward/assignments/B02"
        return httpx.Response(
            200,
            json={
                "v": 1,
                "bed_id": "B02",
                "assigned_nurse": "staff:priya",
                "next_nurse": "staff:ravi",
                "unit_nurses": ["staff:priya", "staff:ravi"],
                "on_call_doctor": "staff:doctor1",
                "assignment_version": "night-1",
                "valid_until": 2_000_000_000_000,
            },
        )

    client = ClinicalBackendClient(
        "https://backend.test", "secret", transport=httpx.MockTransport(handler)
    )
    roster = await client.get_roster("B02")
    assert roster.assigned_nurse == "staff:priya"
    assert roster.all_staff == ("staff:priya", "staff:ravi", "staff:doctor1")


@pytest.mark.asyncio
async def test_waveform_endpoint_rejects_non_png() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["seconds"] == "12"
        return httpx.Response(200, text="not an image")

    client = ClinicalBackendClient(
        "https://backend.test", "secret", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(DeliveryError) as captured:
        await client.get_waveform_png("B02", 1_000)
    assert captured.value.code == "WAVEFORM_SCHEMA_INVALID"


@pytest.mark.asyncio
async def test_telegram_uses_short_deterministic_emergency_user_output() -> None:
    store = InMemoryAlertStore()
    bot = FakeBot()
    notifier = TelegramNotifier(
        bot=bot,  # type: ignore[arg-type]
        identities=TelegramIdentityMap({"staff:priya": 123}),
        store=store,
    )
    alert = AlertRecord(
        alert_id="al_1",
        bed_id="B02",
        verdict=Verdict.EMERGENCY,
        priority="high",
        text="Bed 2 — possible heart emergency. Go now.",
        reasons=["Heart and pulse signals support a real emergency"],
        recipients=["staff:priya"],
        ladder_step=1,
        status="open",
        created_ts=1_000,
        updated_ts=2_000,
        source_window_start=500,
    )

    delivered = await notifier.send(alert.wire(), "staff:priya", waveform_png=None)

    text = bot.messages[0]["text"]
    assert "EMERGENCY ALERT" in text
    assert text.endswith("RESPOND NOW")
    assert "staff:" not in text
    assert "\n" not in text
    assert len(text) <= 160
    assert delivered.message_id == "7"
    assert len(store.callback_targets) == 4


@pytest.mark.asyncio
async def test_opaque_telegram_callback_uses_mapped_staff_identity() -> None:
    store = InMemoryAlertStore()
    token = "opaque-token"
    await store.save_callback_target(
        CallbackTarget(
            token=token,
            alert_id="al_1",
            bed_id="B02",
            alert_updated_ts=2_000,
            action="ack",
        )
    )
    await store.save_alert(
        AlertRecord(
            alert_id="al_1",
            bed_id="B02",
            verdict=Verdict.EMERGENCY,
            priority="high",
            text="Bed 2 — possible heart emergency. Go now.",
            recipients=["staff:priya"],
            ladder_step=1,
            status="open",
            created_ts=1_000,
            updated_ts=2_000,
            source_window_start=500,
        )
    )
    calls: list[dict[str, Any]] = []

    async def acknowledge(alert_id: str, **values: Any) -> None:
        calls.append({"alert_id": alert_id, **values})

    async def escalate(alert_id: str, **values: Any) -> None:
        raise AssertionError((alert_id, values))

    async def publish_bedside(check: BedsideCheckMessage) -> None:
        raise AssertionError(check)

    router = TelegramCallbackRouter(
        store=store,
        identities=TelegramIdentityMap({"staff:priya": 123}),
        acknowledge=acknowledge,
        escalate=escalate,
        publish_bedside=publish_bedside,
    )
    await router(token, "callback-1", "123")
    assert calls[0]["alert_id"] == "al_1"
    assert calls[0]["by"] == "staff:priya"
    assert calls[0]["event_id"].startswith("telegram:")
    assert "opaque-token" not in calls[0]["event_id"]

    with pytest.raises(PermissionError):
        await router(token, "callback-2", "999")


@pytest.mark.asyncio
async def test_stale_bedside_callback_cannot_reopen_closed_event() -> None:
    store = InMemoryAlertStore()
    await store.save_alert(
        AlertRecord(
            alert_id="al_closed",
            bed_id="B02",
            verdict=Verdict.EMERGENCY,
            priority="high",
            text="Bed 2 — possible heart emergency. Go now.",
            recipients=["staff:priya"],
            ladder_step=1,
            status="acknowledged",
            created_ts=1_000,
            updated_ts=2_000,
            source_window_start=500,
            active=False,
        )
    )
    await store.save_callback_target(
        CallbackTarget(
            token="stale-token",
            alert_id="al_closed",
            bed_id="B02",
            alert_updated_ts=1_000,
            action="patient_not_ok",
        )
    )

    async def unused(*args: Any, **kwargs: Any) -> None:
        raise AssertionError((args, kwargs))

    router = TelegramCallbackRouter(
        store=store,
        identities=TelegramIdentityMap({"staff:priya": 123}),
        acknowledge=unused,
        escalate=unused,
        publish_bedside=unused,
    )
    stored = await router("stale-token", "callback-3", "123")
    assert isinstance(stored, AlertRecord)
    assert stored.alert_id == "al_closed"


@pytest.mark.asyncio
async def test_repeated_bedside_token_returns_stored_alert_without_republishing() -> None:
    store = InMemoryAlertStore()
    alert = AlertRecord(
        alert_id="al_1",
        bed_id="B02",
        verdict=Verdict.EMERGENCY,
        priority="high",
        text="Bed 2 — possible heart emergency. Go now.",
        recipients=["staff:priya"],
        ladder_step=1,
        status="open",
        created_ts=1_000,
        updated_ts=2_000,
        source_window_start=500,
    )
    await store.save_alert(alert)
    await store.save_callback_target(
        CallbackTarget(
            token="patient-token",
            alert_id=alert.alert_id,
            bed_id=alert.bed_id,
            alert_updated_ts=alert.updated_ts,
            action="patient_not_ok",
        )
    )
    published: list[BedsideCheckMessage] = []

    async def unused(*args: Any, **kwargs: Any) -> None:
        raise AssertionError((args, kwargs))

    async def publish(check: BedsideCheckMessage) -> None:
        published.append(check)

    router = TelegramCallbackRouter(
        store=store,
        identities=TelegramIdentityMap({"staff:priya": 123}),
        acknowledge=unused,
        escalate=unused,
        publish_bedside=publish,
    )
    first = await router("patient-token", "callback-1", "123")
    repeated = await router("patient-token", "callback-2", "123")

    assert first == alert
    assert repeated == alert
    assert len(published) == 1
