from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pytest

from sentinelward.alert_persistence import InMemoryAlertStore
from sentinelward.alerts import (
    AlertCoordinator,
    DeliveryRecord,
    ProviderMessage,
    RosterSnapshot,
)
from sentinelward.contracts import AlertMessage, BedsideCheckMessage, VerdictMessage


@dataclass
class FakePublisher:
    alerts: list[AlertMessage] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    bedside: list[BedsideCheckMessage] = field(default_factory=list)
    fail_alerts: int = 0

    async def publish_alert(self, alert: AlertMessage) -> None:
        if self.fail_alerts:
            self.fail_alerts -= 1
            raise ConnectionError("controlled screen publish outage")
        self.alerts.append(alert)

    async def publish_action(self, **values: Any) -> None:
        self.actions.append(values)

    async def publish_bedside(self, check: BedsideCheckMessage) -> None:
        self.bedside.append(check)


@dataclass
class FakeNotifier:
    fail: bool = False
    fail_edit: bool = False
    sent: list[tuple[str, str, bool]] = field(default_factory=list)
    edited: list[str] = field(default_factory=list)
    active_edits: list[str] = field(default_factory=list)

    async def send(
        self, alert: AlertMessage, staff_id: str, *, waveform_png: bytes | None
    ) -> ProviderMessage:
        if self.fail:
            raise ConnectionError("controlled Telegram outage")
        self.sent.append((alert.alert_id, staff_id, waveform_png is not None))
        return ProviderMessage(
            message_id=str(len(self.sent)), chat_id=f"9{len(self.sent)}", has_media=True
        )

    async def edit_acknowledged(self, delivery: DeliveryRecord, *, by: str, at_ms: int) -> None:
        del by, at_ms
        if self.fail_edit:
            raise ConnectionError("controlled Telegram edit outage")
        self.edited.append(delivery.delivery_key)

    async def edit_active(self, delivery: DeliveryRecord, alert: AlertMessage) -> None:
        del alert
        if self.fail_edit:
            raise ConnectionError("controlled Telegram edit outage")
        self.active_edits.append(delivery.delivery_key)


@dataclass
class FakeScheduler:
    scheduled: list[tuple[str, int, datetime]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)

    async def schedule(self, alert_id: str, step: int, run_at: datetime) -> None:
        self.scheduled.append((alert_id, step, run_at))

    async def cancel(self, alert_id: str) -> None:
        self.cancelled.append(alert_id)


class FakeRosterProvider:
    def __init__(self, roster: RosterSnapshot) -> None:
        self.roster = roster

    async def get_roster(self, bed_id: str) -> RosterSnapshot:
        assert bed_id == self.roster.bed_id
        return self.roster


class FlakyRosterProvider(FakeRosterProvider):
    def __init__(self, roster: RosterSnapshot) -> None:
        super().__init__(roster)
        self.calls = 0

    async def get_roster(self, bed_id: str) -> RosterSnapshot:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("controlled roster outage")
        return await super().get_roster(bed_id)


class FakeWaveform:
    async def get_waveform_png(self, bed_id: str, end_ts: int) -> bytes:
        del bed_id, end_ts
        return b"png"


@pytest.fixture
def roster() -> RosterSnapshot:
    return RosterSnapshot(
        v=1,
        bed_id="B02",
        assigned_nurse="staff:priya",
        next_nurse="staff:ravi",
        unit_nurses=["staff:priya", "staff:ravi", "staff:asha"],
        on_call_doctor="staff:doctor1",
        assignment_version="night-1",
        valid_until=2_000_000_000_000,
    )


def coordinator(
    roster: RosterSnapshot,
    *,
    notifier: FakeNotifier | None = None,
    publisher: FakePublisher | None = None,
) -> tuple[AlertCoordinator, InMemoryAlertStore, FakePublisher, FakeNotifier, FakeScheduler]:
    store = InMemoryAlertStore()
    alert_publisher = publisher or FakePublisher()
    telegram = notifier or FakeNotifier()
    scheduler = FakeScheduler()
    service = AlertCoordinator(
        store=store,
        publisher=alert_publisher,
        roster_provider=FakeRosterProvider(roster),
        notifier=telegram,
        waveform_provider=FakeWaveform(),
        scheduler=scheduler,
        escalation_seconds=30,
        clock=lambda: 1_000_000,
    )
    return service, store, alert_publisher, telegram, scheduler


@pytest.mark.asyncio
async def test_high_alert_climbs_three_step_ladder_and_ack_stops_it(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, store, publisher, telegram, scheduler = coordinator(roster)
    verdict = VerdictMessage.model_validate(contract_fixture["verdicts"][1]).model_copy(
        update={"bed_id": "B02"}
    )

    step1 = await service.handle_verdict(verdict)
    assert step1 is not None
    assert step1.recipients == ["staff:priya"]
    assert scheduler.scheduled[-1][1] == 2

    step2 = await service.escalate_due(step1.alert_id, 2)
    assert step2 is not None
    assert step2.recipients == ["staff:priya", "staff:ravi"]
    assert scheduler.scheduled[-1][1] == 3

    step3 = await service.escalate_due(step1.alert_id, 3)
    assert step3 is not None
    assert step3.ladder_step == 3
    assert step3.recipients == [
        "staff:priya",
        "staff:ravi",
        "staff:asha",
        "staff:doctor1",
    ]

    acknowledged = await service.acknowledge(
        step1.alert_id,
        by="staff:asha",
        at_ms=1_015_000,
        event_id="screen-ack-1",
    )
    assert acknowledged.status == "acknowledged"
    assert acknowledged.response_ms == 15_000
    assert scheduler.cancelled == [step1.alert_id]
    assert len(telegram.edited) == 4
    assert publisher.alerts[-1].acked_by == "staff:asha"
    assert (await store.get_alert(step1.alert_id)) == acknowledged


@pytest.mark.asyncio
async def test_repeated_verdict_updates_one_alert(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, store, _, telegram, scheduler = coordinator(roster)
    verdict = VerdictMessage.model_validate(contract_fixture["verdicts"][1])
    first = await service.handle_verdict(verdict)
    repeated = await service.handle_verdict(
        verdict.model_copy(
            update={"ts": verdict.ts + 5_000, "window_start": verdict.window_start + 5_000}
        )
    )
    assert first is not None and repeated is not None
    assert repeated.alert_id == first.alert_id
    assert len(store.alerts) == 1
    assert len(telegram.sent) == 1
    assert len(telegram.active_edits) == 1
    assert len(scheduler.scheduled) == 1


@pytest.mark.asyncio
async def test_repeated_verdict_refreshes_reasons_text_and_delivery_state(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, store, publisher, telegram, _ = coordinator(roster)
    verdict = VerdictMessage.model_validate(contract_fixture["verdicts"][5]).model_copy(
        update={"bed_id": "B02"}
    )
    first = await service.handle_verdict(verdict)
    assert first is not None
    updated_reason = "Arterial pressure gap increased to 15 mmHg"

    repeated = await service.handle_verdict(
        verdict.model_copy(
            update={
                "ts": verdict.ts + 5_000,
                "window_start": verdict.window_start + 5_000,
                "reasons": [updated_reason],
            }
        )
    )

    assert repeated is not None
    assert repeated.alert_id == first.alert_id
    assert repeated.reasons == [updated_reason]
    assert updated_reason in repeated.text
    assert telegram.active_edits == [f"{first.alert_id}:staff:priya"]
    delivery = (await store.list_deliveries(first.alert_id))[0]
    assert delivery.status == "delivered"
    assert publisher.actions[-1]["action"] == "edit_message"
    assert publisher.actions[-1]["result"] == "ok"


@pytest.mark.asyncio
async def test_higher_priority_verdict_upgrades_same_alert(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, _, publisher, _, scheduler = coordinator(roster)
    medium = VerdictMessage.model_validate(contract_fixture["verdicts"][3]).model_copy(
        update={"bed_id": "B02"}
    )
    high = VerdictMessage.model_validate(contract_fixture["verdicts"][1]).model_copy(
        update={"bed_id": "B02", "ts": medium.ts + 5_000, "window_start": medium.ts + 5_000}
    )

    initial = await service.handle_verdict(medium)
    upgraded = await service.handle_verdict(high)

    assert initial is not None and upgraded is not None
    assert upgraded.alert_id == initial.alert_id
    assert upgraded.priority == "high"
    assert upgraded.verdict == high.verdict
    assert upgraded.reasons == high.reasons
    assert publisher.alerts[-1].alert_id == initial.alert_id
    assert scheduler.scheduled[-1][1] == 2


@pytest.mark.asyncio
async def test_manual_escalation_replaces_timer_and_starts_next_delay_from_click(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, _, _, telegram, scheduler = coordinator(roster)
    alert = await service.handle_verdict(
        VerdictMessage.model_validate(contract_fixture["verdicts"][1]).model_copy(
            update={"bed_id": "B02"}
        )
    )
    assert alert is not None

    advanced = await service.escalate(
        alert.alert_id,
        by="staff:priya",
        at_ms=1_010_000,
        event_id="manual-escalate-1",
    )

    assert advanced.ladder_step == 2
    assert scheduler.cancelled == [alert.alert_id]
    assert scheduler.scheduled[-1][1] == 3
    assert int(scheduler.scheduled[-1][2].timestamp() * 1000) == 1_040_000
    assert [staff_id for _, staff_id, _ in telegram.sent] == [
        "staff:priya",
        "staff:ravi",
    ]


@pytest.mark.asyncio
async def test_medium_alert_notifies_once_without_timer(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, _, _, telegram, scheduler = coordinator(roster)
    verdict = VerdictMessage.model_validate(contract_fixture["verdicts"][3]).model_copy(
        update={"bed_id": "B02"}
    )
    alert = await service.handle_verdict(verdict)
    assert alert is not None
    assert alert.priority == "medium"
    assert [item[1] for item in telegram.sent] == ["staff:priya"]
    assert scheduler.scheduled == []


@pytest.mark.asyncio
async def test_phone_failure_does_not_remove_screen_alert(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, store, publisher, _, _ = coordinator(roster, notifier=FakeNotifier(fail=True))
    verdict = VerdictMessage.model_validate(contract_fixture["verdicts"][1])
    alert = await service.handle_verdict(verdict)
    assert alert is not None
    assert publisher.alerts[0].status == "open"
    deliveries = await store.list_deliveries(alert.alert_id)
    assert deliveries[0].status == "failed"
    assert publisher.actions[-1]["result"] == "failed"


@pytest.mark.asyncio
async def test_telegram_edit_outcomes_are_published_without_failing_clinical_alert(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    notifier = FakeNotifier(fail_edit=True)
    service, store, publisher, _, _ = coordinator(roster, notifier=notifier)
    verdict = VerdictMessage.model_validate(contract_fixture["verdicts"][1]).model_copy(
        update={"bed_id": "B02"}
    )
    first = await service.handle_verdict(verdict)
    assert first is not None

    repeated = await service.handle_verdict(
        verdict.model_copy(update={"ts": verdict.ts + 1_000, "window_start": verdict.ts + 1_000})
    )

    assert repeated is not None
    assert repeated.status == "open"
    assert (await store.get_alert(repeated.alert_id)).status == "open"
    assert any(
        action["action"] == "edit_message" and action["result"] == "failed"
        for action in publisher.actions
    )


@pytest.mark.asyncio
async def test_repeated_verdict_recovers_phone_routing_after_roster_outage(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    store = InMemoryAlertStore()
    publisher = FakePublisher()
    telegram = FakeNotifier()
    scheduler = FakeScheduler()
    service = AlertCoordinator(
        store=store,
        publisher=publisher,
        roster_provider=FlakyRosterProvider(roster),
        notifier=telegram,
        waveform_provider=FakeWaveform(),
        scheduler=scheduler,
        escalation_seconds=30,
        clock=lambda: 1_000_000,
    )
    verdict = VerdictMessage.model_validate(contract_fixture["verdicts"][1])

    first = await service.handle_verdict(verdict)
    assert first is not None and first.recipients == []
    assert telegram.sent == []

    recovered = await service.handle_verdict(
        verdict.model_copy(
            update={"ts": verdict.ts + 5_000, "window_start": verdict.window_start + 5_000}
        )
    )
    assert recovered is not None
    assert recovered.recipients == ["staff:priya"]
    assert [item[1] for item in telegram.sent] == ["staff:priya"]


@pytest.mark.asyncio
async def test_retry_after_screen_publish_crash_reuses_alert_and_sends_phone_once(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    publisher = FakePublisher(fail_alerts=1)
    service, store, _, telegram, scheduler = coordinator(roster, publisher=publisher)
    verdict = VerdictMessage.model_validate(contract_fixture["verdicts"][1])

    with pytest.raises(ConnectionError, match="screen publish outage"):
        await service.handle_verdict(verdict)
    persisted = await store.get_active_alert("B02")
    assert persisted is not None
    assert telegram.sent == []

    recovered = await service.handle_verdict(verdict)
    assert recovered is not None
    assert recovered.alert_id == persisted.alert_id
    assert len(telegram.sent) == 1
    assert scheduler.scheduled[-1][1] == 2


@pytest.mark.asyncio
async def test_patient_ok_closes_but_patient_not_ok_keeps_high_ladder(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, store, _, _, scheduler = coordinator(roster)
    unsure = VerdictMessage.model_validate(contract_fixture["verdicts"][4]).model_copy(
        update={"bed_id": "B02"}
    )
    alert = await service.handle_verdict(unsure)
    assert alert is not None
    closed = await service.handle_bedside(
        BedsideCheckMessage(
            v=1,
            type="bedside_check",
            bed_id="B02",
            ts=1_010_000,
            result="patient_ok",
            by="staff:priya",
        )
    )
    assert closed is not None and closed.active is False

    high = await service.handle_bedside(
        BedsideCheckMessage(
            v=1,
            type="bedside_check",
            bed_id="B02",
            ts=1_020_000,
            result="patient_not_ok",
            by="staff:priya",
        )
    )
    assert high is not None
    assert high.priority == "high"
    assert high.status == "open"
    assert high.active is True
    assert scheduler.scheduled[-1][1] == 2
    assert await store.get_active_alert("B02") == high


@pytest.mark.asyncio
async def test_normal_keeps_unacknowledged_alert_but_rearms_after_acknowledgement(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, store, _, _, _ = coordinator(roster)
    emergency = VerdictMessage.model_validate(contract_fixture["verdicts"][1]).model_copy(
        update={"bed_id": "B02"}
    )
    normal = VerdictMessage.model_validate(contract_fixture["verdicts"][0]).model_copy(
        update={"bed_id": "B02"}
    )
    first = await service.handle_verdict(emergency)
    assert first is not None

    assert await service.handle_verdict(normal) is None
    still_active = await store.get_active_alert("B02")
    assert still_active is not None
    assert still_active.alert_id == first.alert_id
    assert still_active.status == "open"
    assert still_active.normal_seen is True

    acknowledged = await service.acknowledge(
        first.alert_id,
        by="staff:priya",
        at_ms=1_010_000,
        event_id="ack-before-normal",
    )
    assert acknowledged.active is True
    assert await service.handle_verdict(normal) is None
    assert await store.get_active_alert("B02") is None

    future = await service.handle_verdict(
        emergency.model_copy(
            update={"ts": emergency.ts + 60_000, "window_start": emergency.window_start + 60_000}
        )
    )
    assert future is not None
    assert future.alert_id != first.alert_id


@pytest.mark.asyncio
async def test_unauthorized_ack_is_rejected(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, _, _, _, _ = coordinator(roster)
    alert = await service.handle_verdict(
        VerdictMessage.model_validate(contract_fixture["verdicts"][1])
    )
    assert alert is not None
    with pytest.raises(PermissionError, match="not on the current alert roster"):
        await service.acknowledge(
            alert.alert_id,
            by="staff:intruder",
            at_ms=1_005_000,
            event_id="forged",
        )


@pytest.mark.asyncio
async def test_completed_duplicate_ack_returns_stored_result_without_repeating_effects(
    contract_fixture: dict[str, Any], roster: RosterSnapshot
) -> None:
    service, _, publisher, telegram, scheduler = coordinator(roster)
    alert = await service.handle_verdict(
        VerdictMessage.model_validate(contract_fixture["verdicts"][1]).model_copy(
            update={"bed_id": "B02"}
        )
    )
    assert alert is not None
    first = await service.acknowledge(
        alert.alert_id,
        by="staff:priya",
        at_ms=1_005_000,
        event_id="same-ack",
    )
    counts = (
        len(publisher.alerts),
        len(publisher.actions),
        len(telegram.edited),
        len(scheduler.cancelled),
    )

    repeated = await service.acknowledge(
        alert.alert_id,
        by="staff:priya",
        at_ms=1_005_000,
        event_id="same-ack",
    )

    assert repeated == first
    assert counts == (
        len(publisher.alerts),
        len(publisher.actions),
        len(telegram.edited),
        len(scheduler.cancelled),
    )
