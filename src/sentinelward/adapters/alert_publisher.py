from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, Protocol

from sentinelward.alerts import AlertRecord
from sentinelward.contracts import ActionMessage, AlertMessage, BedsideCheckMessage
from sentinelward.health import HealthRegistry
from sentinelward.ports import FoundationStore


class MqttPublisherPort(Protocol):
    async def publish(
        self, topic: str, payload: bytes, *, qos: int = 1, retain: bool = False
    ) -> None: ...


@dataclass(slots=True)
class MqttAlertPublisher:
    store: FoundationStore

    async def retire_alert(self, alert_id: str) -> None:
        await self.store.retire_alert_outbox(alert_id)

    async def publish_alert(self, alert: AlertMessage) -> None:
        body = alert.model_dump(mode="json")
        await self._enqueue(
            topic="ward/alert",
            body=body,
            correlation_id=alert.alert_id,
            identity=f"alert:{alert.alert_id}:{alert.ts}:{alert.ladder_step}:{alert.status}",
        )

    async def publish_action(
        self,
        *,
        alert: AlertRecord,
        action: str,
        result: Literal["ok", "failed", "pending", "unknown"],
        detail: str,
        approved_by: str | None = None,
    ) -> None:
        identity = stable_identity(
            alert.alert_id,
            str(alert.updated_ts),
            action,
            result,
            detail,
            approved_by or "",
        )
        message = ActionMessage(
            v=1,
            type="action",
            action_id=f"act_{identity[:32]}",
            ts=alert.updated_ts,
            by="A1",
            action=action,
            bed_id=alert.bed_id,
            device_id=None,
            detail=detail[:240],
            undo_id=None,
            undoes=None,
            approved_by=approved_by,
            result=result,
        )
        await self._enqueue(
            topic="ward/action",
            body=message.model_dump(mode="json"),
            correlation_id=alert.alert_id,
            identity=f"action:{identity}",
        )

    async def publish_bedside(self, check: BedsideCheckMessage) -> None:
        topic = f"ward/bed/{check.bed_id}/bedside"
        await self._enqueue(
            topic=topic,
            body=check.model_dump(mode="json"),
            correlation_id=f"{check.bed_id}:{check.ts}:bedside",
            identity=f"bedside:{check.bed_id}:{check.ts}:{check.by}:{check.result}",
        )

    async def _enqueue(
        self,
        *,
        topic: str,
        body: dict[str, object],
        correlation_id: str,
        identity: str,
    ) -> None:
        await self.store.enqueue_outbox(
            delivery_key=f"mqtt:{stable_identity(identity, canonical_json(body))}",
            destination=f"mqtt:{topic}",
            payload={"topic": topic, "body": body, "qos": 1},
            correlation_id=correlation_id,
        )


@dataclass(slots=True)
class MqttOutboxWorker:
    store: FoundationStore
    mqtt: MqttPublisherPort
    poll_seconds: float = 0.25
    health: HealthRegistry | None = None
    _stopping: asyncio.Event = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        while not self._stopping.is_set():
            events = await self.store.due_mqtt_outbox()
            if not events:
                await asyncio.sleep(self.poll_seconds)
                continue
            for event in events:
                await self._deliver(event)

    async def stop(self) -> None:
        self._stopping.set()

    async def _deliver(self, event: dict[str, object]) -> None:
        delivery_key = str(event["delivery_key"])
        if not await self.store.outbox_is_pending(delivery_key):
            return
        payload = event.get("payload")
        if not isinstance(payload, dict):
            await self.store.reschedule_outbox(
                delivery_key, error="outbox payload is not an object", delay_seconds=30
            )
            return
        topic = payload.get("topic")
        body = payload.get("body")
        if not isinstance(topic, str) or not isinstance(body, dict):
            await self.store.reschedule_outbox(
                delivery_key, error="outbox MQTT payload is invalid", delay_seconds=30
            )
            return
        try:
            await self.mqtt.publish(
                topic,
                json.dumps(body, separators=(",", ":"), sort_keys=True).encode(),
                qos=1,
                retain=False,
            )
        except Exception as exc:
            raw_attempts = event.get("attempt_count", 0)
            attempts = raw_attempts if isinstance(raw_attempts, int) else 0
            await self.store.reschedule_outbox(
                delivery_key,
                error=f"{type(exc).__name__}: {exc}",
                delay_seconds=min(30, 2 ** min(attempts, 5)),
            )
            if self.health is not None:
                self.health.increment("outbox_retry")
            return
        await self.store.mark_outbox_delivered(delivery_key)
        if self.health is not None:
            self.health.increment("outbox_delivered")


def stable_identity(*values: str) -> str:
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()


def canonical_json(value: dict[str, object]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
