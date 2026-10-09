from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from sentinelward.contracts import (
    AlertMessage,
    BedId,
    BedsideCheckMessage,
    Reason,
    StaffId,
    Verdict,
    VerdictMessage,
)


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class RosterSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    v: Literal[1] = 1
    bed_id: BedId
    assigned_nurse: StaffId
    next_nurse: StaffId
    unit_nurses: list[StaffId] = Field(min_length=1)
    on_call_doctor: StaffId
    assignment_version: str = Field(min_length=1, max_length=96)
    valid_until: int = Field(ge=0)

    @property
    def all_staff(self) -> tuple[str, ...]:
        return unique_people(
            [self.assigned_nurse, self.next_nurse, *self.unit_nurses, self.on_call_doctor]
        )


class AlertRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: str
    bed_id: BedId
    verdict: Verdict
    priority: Literal["low", "medium", "high"]
    text: str = Field(min_length=1, max_length=240)
    reasons: list[Reason] = Field(default_factory=list, max_length=3)
    recipients: list[StaffId]
    ladder_step: int = Field(ge=1, le=3)
    status: Literal["open", "escalated", "acknowledged", "failed"]
    created_ts: int = Field(ge=0)
    updated_ts: int = Field(ge=0)
    source_window_start: int = Field(ge=0)
    roster: RosterSnapshot | None = None
    next_escalation_ts: int | None = Field(default=None, ge=0)
    acked_by: StaffId | None = None
    acked_ts: int | None = Field(default=None, ge=0)
    response_ms: int | None = Field(default=None, ge=0)
    active: bool = True
    normal_seen: bool = False
    ack_finalized: bool = False

    def wire(self) -> AlertMessage:
        return AlertMessage(
            v=1,
            type="alert",
            alert_id=self.alert_id,
            ts=self.updated_ts,
            bed_id=self.bed_id,
            verdict=self.verdict,
            priority=self.priority,
            text=self.text,
            to=self.recipients,
            ladder_step=self.ladder_step,
            status=self.status,
            acked_by=self.acked_by,
            acked_ts=self.acked_ts,
        )


class DeliveryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    delivery_key: str
    alert_id: str
    staff_id: StaffId
    status: Literal["pending", "delivered", "failed"]
    attempt_count: int = Field(default=0, ge=0)
    next_attempt_ts: int | None = Field(default=None, ge=0)
    provider_message_id: str | None = None
    provider_chat_id: str | None = None
    has_media: bool = False
    last_error: str | None = Field(default=None, max_length=240)


class ProviderMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: str
    chat_id: str
    has_media: bool = False


class CallbackTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    token: str
    alert_id: str
    bed_id: BedId
    alert_updated_ts: int = Field(ge=0)
    action: Literal["ack", "escalate", "patient_ok", "patient_not_ok"]


class AlertStore(Protocol):
    async def get_active_alert(self, bed_id: str) -> AlertRecord | None: ...

    async def get_alert(self, alert_id: str) -> AlertRecord | None: ...

    async def save_alert(self, alert: AlertRecord) -> None: ...

    async def record_callback(self, event_id: str, alert_id: str) -> bool: ...

    async def save_delivery(self, delivery: DeliveryRecord) -> None: ...

    async def list_deliveries(self, alert_id: str) -> list[DeliveryRecord]: ...

    async def get_cached_roster(self, bed_id: str, at_ms: int) -> RosterSnapshot | None: ...

    async def save_roster(self, roster: RosterSnapshot) -> None: ...

    async def save_callback_target(self, target: CallbackTarget) -> None: ...

    async def get_callback_target(self, token: str) -> CallbackTarget | None: ...


class AlertPublisher(Protocol):
    async def publish_alert(self, alert: AlertMessage) -> None: ...

    async def publish_action(
        self,
        *,
        alert: AlertRecord,
        action: str,
        result: Literal["ok", "failed", "pending", "unknown"],
        detail: str,
        approved_by: str | None = None,
    ) -> None: ...

    async def publish_bedside(self, check: BedsideCheckMessage) -> None: ...


class RosterProvider(Protocol):
    async def get_roster(self, bed_id: str) -> RosterSnapshot: ...


class WaveformProvider(Protocol):
    async def get_waveform_png(self, bed_id: str, end_ts: int) -> bytes | None: ...


class NotificationPort(Protocol):
    async def send(
        self, alert: AlertMessage, staff_id: str, *, waveform_png: bytes | None
    ) -> ProviderMessage: ...

    async def edit_acknowledged(self, delivery: DeliveryRecord, *, by: str, at_ms: int) -> None: ...

    async def edit_active(self, delivery: DeliveryRecord, alert: AlertMessage) -> None: ...


class AlertScheduler(Protocol):
    async def schedule(self, alert_id: str, step: int, run_at: datetime) -> None: ...

    async def cancel(self, alert_id: str) -> None: ...


class AlertCoordinator:
    def __init__(
        self,
        *,
        store: AlertStore,
        publisher: AlertPublisher,
        roster_provider: RosterProvider,
        notifier: NotificationPort,
        waveform_provider: WaveformProvider,
        scheduler: AlertScheduler,
        escalation_seconds: int,
        clock: Callable[[], int] = now_ms,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._roster_provider = roster_provider
        self._notifier = notifier
        self._waveform_provider = waveform_provider
        self._scheduler = scheduler
        self._escalation_seconds = escalation_seconds
        self._clock = clock
        self._transition_lock = asyncio.Lock()

    async def handle_verdict(self, verdict: VerdictMessage) -> AlertRecord | None:
        async with self._transition_lock:
            return await self._handle_verdict(verdict)

    async def _handle_verdict(self, verdict: VerdictMessage) -> AlertRecord | None:
        if verdict.verdict in {Verdict.NORMAL, Verdict.DEVICE_ATTACK}:
            if verdict.verdict == Verdict.NORMAL:
                await self._handle_normal(verdict.bed_id)
            return None
        assert verdict.priority != "none"

        current = await self._store.get_active_alert(verdict.bed_id)
        timestamp = self._clock()
        is_high = verdict.priority == "high"
        if current is None:
            roster = await self._resolve_roster(verdict.bed_id, timestamp)
            recipients = [roster.assigned_nurse] if roster else []
            alert = AlertRecord(
                alert_id=f"al_{uuid4().hex}",
                bed_id=verdict.bed_id,
                verdict=verdict.verdict,
                priority=verdict.priority,
                text=message_for(verdict.verdict, verdict.bed_id, verdict.reasons),
                reasons=list(verdict.reasons),
                recipients=recipients,
                ladder_step=1,
                status="open",
                created_ts=timestamp,
                updated_ts=timestamp,
                source_window_start=verdict.window_start,
                roster=roster,
            )
            await self._store.save_alert(alert)
            await self._publisher.publish_alert(alert.wire())
            await self._notify_new_recipients(alert, recipients)
            if is_high:
                alert = await self._schedule_next(alert, 2)
            return alert

        was_high = current.priority == "high"
        roster = current.roster
        recipients = list(current.recipients)
        if roster is None:
            roster = await self._resolve_roster(verdict.bed_id, timestamp)
            if roster is not None and not recipients:
                recipients = [roster.assigned_nurse]
        accept_incoming = priority_rank(verdict.priority) >= priority_rank(current.priority)
        alert = current.model_copy(
            update={
                "verdict": verdict.verdict if accept_incoming else current.verdict,
                "priority": max_priority(current.priority, verdict.priority),
                "text": (
                    message_for(verdict.verdict, verdict.bed_id, verdict.reasons)
                    if accept_incoming
                    else current.text
                ),
                "reasons": list(verdict.reasons) if accept_incoming else current.reasons,
                "updated_ts": timestamp,
                "source_window_start": verdict.window_start,
                "normal_seen": False,
                "roster": roster,
                "recipients": recipients,
            }
        )
        await self._store.save_alert(alert)
        await self._publisher.publish_alert(alert.wire())
        await self._refresh_existing_deliveries(alert)
        await self._notify_missing_recipients(alert)
        if (
            is_high
            and alert.status != "acknowledged"
            and (not was_high or alert.next_escalation_ts is None)
        ):
            alert = await self._schedule_next(alert, 2)
        return alert

    async def handle_bedside(self, check: BedsideCheckMessage) -> AlertRecord | None:
        async with self._transition_lock:
            active = await self._store.get_active_alert(check.bed_id)
            if (
                active is not None
                and active.roster is not None
                and check.by not in active.roster.all_staff
            ):
                raise PermissionError("bedside staff member is not on the current alert roster")
            if check.result == "patient_ok":
                if active is None:
                    return None
                return await self._acknowledge(
                    active,
                    by=check.by,
                    at_ms=check.ts,
                    event_id=f"bedside:{check.bed_id}:{check.ts}:{check.by}",
                    close=True,
                )

            synthetic = VerdictMessage(
                v=1,
                type="verdict",
                bed_id=check.bed_id,
                ts=check.ts,
                window_start=check.ts,
                verdict=Verdict.EMERGENCY,
                priority="high",
                confidence=1.0,
                trust=0.5,
                last_trusted_ts=None,
                reasons=["Bedside nurse reports patient not OK"],
                scores={},
            )
            return await self._handle_verdict(synthetic)

    async def acknowledge(
        self, alert_id: str, *, by: str, at_ms: int, event_id: str
    ) -> AlertRecord:
        async with self._transition_lock:
            alert = await self._require_alert(alert_id)
            if alert.roster is not None and by not in alert.roster.all_staff:
                raise PermissionError(
                    "acknowledging staff member is not on the current alert roster"
                )
            return await self._acknowledge(
                alert, by=by, at_ms=at_ms, event_id=event_id, close=False
            )

    async def escalate(self, alert_id: str, *, by: str, at_ms: int, event_id: str) -> AlertRecord:
        async with self._transition_lock:
            alert = await self._require_alert(alert_id)
            if alert.roster is not None and by not in alert.roster.all_staff:
                raise PermissionError("escalating staff member is not on the current alert roster")
            if not await self._store.record_callback(event_id, alert_id):
                return alert
            if alert.status == "acknowledged" or alert.ladder_step == 3:
                return alert
            await self._scheduler.cancel(alert.alert_id)
            return await self._advance(alert, alert.ladder_step + 1, at_ms=at_ms)

    async def escalate_due(self, alert_id: str, expected_step: int) -> AlertRecord | None:
        async with self._transition_lock:
            alert = await self._store.get_alert(alert_id)
            if alert is None or not alert.active or alert.status == "acknowledged":
                return alert
            if expected_step != alert.ladder_step + 1:
                return alert
            return await self._advance(alert, expected_step, at_ms=self._clock())

    async def _advance(self, alert: AlertRecord, step: int, *, at_ms: int) -> AlertRecord:
        if alert.roster is None:
            return alert
        new_recipients = recipients_for_step(alert.roster, step)
        cumulative = list(unique_people([*alert.recipients, *new_recipients]))
        updated = alert.model_copy(
            update={
                "recipients": cumulative,
                "ladder_step": step,
                "status": "escalated",
                "updated_ts": at_ms,
                "next_escalation_ts": None,
            }
        )
        await self._store.save_alert(updated)
        await self._publisher.publish_alert(updated.wire())
        await self._publisher.publish_action(
            alert=updated,
            action="escalate",
            result="ok",
            detail=f"A1 advanced {updated.alert_id} to ladder step {step}",
        )
        already = set(alert.recipients)
        await self._notify_new_recipients(
            updated, [person for person in new_recipients if person not in already]
        )
        if step < 3:
            updated = await self._schedule_next(updated, step + 1)
        return updated

    async def _acknowledge(
        self,
        alert: AlertRecord,
        *,
        by: str,
        at_ms: int,
        event_id: str,
        close: bool,
    ) -> AlertRecord:
        recorded = await self._store.record_callback(event_id, alert.alert_id)
        if not recorded:
            if alert.status == "acknowledged" and not alert.ack_finalized:
                return await self._finalize_ack(alert)
            return alert
        if alert.status == "acknowledged":
            return alert
        timestamp = max(at_ms, alert.created_ts)
        updated = alert.model_copy(
            update={
                "status": "acknowledged",
                "acked_by": by,
                "acked_ts": timestamp,
                "response_ms": timestamp - alert.created_ts,
                "updated_ts": timestamp,
                "next_escalation_ts": None,
                "active": not close,
                "ack_finalized": False,
            }
        )
        await self._store.save_alert(updated)
        return await self._finalize_ack(updated)

    async def _finalize_ack(self, alert: AlertRecord) -> AlertRecord:
        if alert.acked_by is None or alert.acked_ts is None:
            raise ValueError("acknowledged alert is missing acknowledgement identity")
        await self._scheduler.cancel(alert.alert_id)
        await self._publisher.publish_alert(alert.wire())
        await self._publisher.publish_action(
            alert=alert,
            action="record_ack",
            result="ok",
            detail=f"Acknowledged by {alert.acked_by} in {alert.response_ms} ms",
            approved_by=alert.acked_by,
        )
        for delivery in await self._store.list_deliveries(alert.alert_id):
            if delivery.provider_message_id is None or delivery.provider_chat_id is None:
                continue
            try:
                await self._notifier.edit_acknowledged(
                    delivery, by=alert.acked_by, at_ms=alert.acked_ts
                )
                await self._store.save_delivery(
                    delivery.model_copy(update={"status": "delivered", "last_error": None})
                )
                await self._publisher.publish_action(
                    alert=alert,
                    action="edit_message",
                    result="ok",
                    detail=f"Acknowledgement shown to {delivery.staff_id}",
                )
            except Exception as exc:
                failed = delivery.model_copy(
                    update={"status": "failed", "last_error": safe_error(exc)}
                )
                await self._store.save_delivery(failed)
                await self._publisher.publish_action(
                    alert=alert,
                    action="edit_message",
                    result="failed",
                    detail=f"Acknowledgement edit failed for {delivery.staff_id}",
                )
        finalized = alert.model_copy(update={"ack_finalized": True})
        await self._store.save_alert(finalized)
        return finalized

    async def _handle_normal(self, bed_id: str) -> None:
        active = await self._store.get_active_alert(bed_id)
        if active is None:
            return
        if active.status == "acknowledged":
            updated = active.model_copy(
                update={"active": False, "normal_seen": True, "updated_ts": self._clock()}
            )
        else:
            updated = active.model_copy(update={"normal_seen": True, "updated_ts": self._clock()})
        await self._store.save_alert(updated)

    async def _notify_new_recipients(self, alert: AlertRecord, recipients: Sequence[str]) -> None:
        waveform = None
        if alert.priority == "high" and recipients:
            try:
                waveform = await self._waveform_provider.get_waveform_png(
                    alert.bed_id, alert.updated_ts
                )
            except Exception:
                waveform = None
        for staff_id in recipients:
            delivery_key = f"{alert.alert_id}:{staff_id}"
            pending = DeliveryRecord(
                delivery_key=delivery_key,
                alert_id=alert.alert_id,
                staff_id=staff_id,
                status="pending",
            )
            await self._store.save_delivery(pending)
            try:
                provider = await self._notifier.send(alert.wire(), staff_id, waveform_png=waveform)
            except Exception as exc:
                failed = pending.model_copy(
                    update={
                        "status": "failed",
                        "attempt_count": 1,
                        "next_attempt_ts": None,
                        "last_error": safe_error(exc),
                    }
                )
                await self._store.save_delivery(failed)
                await self._publisher.publish_action(
                    alert=alert,
                    action="send_message",
                    result="failed",
                    detail=f"Phone delivery failed for {staff_id}",
                )
                continue
            delivered = pending.model_copy(
                update={
                    "status": "delivered",
                    "attempt_count": 1,
                    "provider_message_id": provider.message_id,
                    "provider_chat_id": provider.chat_id,
                    "has_media": provider.has_media,
                }
            )
            await self._store.save_delivery(delivered)
            await self._publisher.publish_action(
                alert=alert,
                action="send_message",
                result="ok",
                detail=f"Phone backup delivered to {staff_id}",
            )

    async def _notify_missing_recipients(self, alert: AlertRecord) -> None:
        existing = {
            delivery.staff_id for delivery in await self._store.list_deliveries(alert.alert_id)
        }
        await self._notify_new_recipients(
            alert, [staff_id for staff_id in alert.recipients if staff_id not in existing]
        )

    async def _refresh_existing_deliveries(self, alert: AlertRecord) -> None:
        for delivery in await self._store.list_deliveries(alert.alert_id):
            if delivery.provider_message_id is None or delivery.provider_chat_id is None:
                continue
            try:
                await self._notifier.edit_active(delivery, alert.wire())
                await self._store.save_delivery(
                    delivery.model_copy(update={"status": "delivered", "last_error": None})
                )
                await self._publisher.publish_action(
                    alert=alert,
                    action="edit_message",
                    result="ok",
                    detail=f"Active alert updated for {delivery.staff_id}",
                )
            except Exception as exc:
                await self._store.save_delivery(
                    delivery.model_copy(update={"status": "failed", "last_error": safe_error(exc)})
                )
                await self._publisher.publish_action(
                    alert=alert,
                    action="edit_message",
                    result="failed",
                    detail=f"Active alert edit failed for {delivery.staff_id}",
                )

    async def _schedule_next(self, alert: AlertRecord, step: int) -> AlertRecord:
        due = datetime.fromtimestamp(alert.updated_ts / 1000, tz=UTC) + timedelta(
            seconds=self._escalation_seconds
        )
        updated = alert.model_copy(update={"next_escalation_ts": int(due.timestamp() * 1000)})
        await self._scheduler.schedule(updated.alert_id, step, due)
        await self._store.save_alert(updated)
        return updated

    async def _resolve_roster(self, bed_id: str, timestamp: int) -> RosterSnapshot | None:
        try:
            roster = await self._roster_provider.get_roster(bed_id)
        except Exception:
            return await self._store.get_cached_roster(bed_id, timestamp)
        if roster.valid_until < timestamp:
            return await self._store.get_cached_roster(bed_id, timestamp)
        await self._store.save_roster(roster)
        return roster

    async def _require_alert(self, alert_id: str) -> AlertRecord:
        alert = await self._store.get_alert(alert_id)
        if alert is None:
            raise LookupError(f"unknown alert {alert_id}")
        return alert


class CallbackHandler(Protocol):
    async def __call__(self, action: str, token: str, callback_id: str, chat_id: str) -> None: ...


def message_for(verdict: Verdict, bed_id: str, reasons: Sequence[str]) -> str:
    bed = str(int(bed_id[1:]))
    reason = reasons[0] if reasons else "Check the patient and monitor"
    templates = {
        Verdict.EMERGENCY: f"Bed {bed} — possible heart emergency. Go now.",
        Verdict.BOTH: f"Bed {bed} — emergency possible and monitor untrusted. Go now.",
        Verdict.TAMPERING: f"Bed {bed} — monitor cannot be trusted. Check by hand now.",
        Verdict.UNSURE: f"Bed {bed} — readings are unclear. Check the patient by hand.",
        Verdict.DRIFTING: f"Bed {bed} — blood pressure sensor may be drifting. {reason}",
        Verdict.LOOSE_SENSOR: f"Bed {bed} — sensor may be loose. Refit and check the patient.",
    }
    return templates[verdict][:240]


def recipients_for_step(roster: RosterSnapshot, step: int) -> tuple[str, ...]:
    if step == 1:
        return (roster.assigned_nurse,)
    if step == 2:
        return (roster.next_nurse,)
    if step == 3:
        return unique_people([*roster.unit_nurses, roster.on_call_doctor])
    raise ValueError("ladder step must be between 1 and 3")


def unique_people(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def max_priority(
    current: Literal["low", "medium", "high"], incoming: Literal["low", "medium", "high"]
) -> Literal["low", "medium", "high"]:
    order = {"low": 0, "medium": 1, "high": 2}
    return current if order[current] >= order[incoming] else incoming


def priority_rank(value: str) -> int:
    return {"none": -1, "low": 0, "medium": 1, "high": 2}[value]


def safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:240]


EscalationHandler = Callable[[str, int], Awaitable[AlertRecord | None]]
