from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from sentinelward.config import Settings
from sentinelward.contracts import (
    BedsideCheckMessage,
    DemoControlMessage,
    RequestMessage,
    ScoreMessage,
    VerdictMessage,
    VitalsMessage,
    correlation_id_for,
    ingress_idempotency_key,
    parse_wire_message,
)
from sentinelward.errors import ContractError
from sentinelward.health import HealthRegistry
from sentinelward.ports import FoundationStore, WorkflowEngine

LOGGER = logging.getLogger(__name__)


class BedsideHandler(Protocol):
    async def handle_bedside(self, check: BedsideCheckMessage) -> object: ...


class M6Handler(Protocol):
    async def handle_m6(self, message: VitalsMessage | ScoreMessage) -> ScoreMessage | None: ...


class DemoControlHandler(Protocol):
    async def handle_control(self, command: DemoControlMessage) -> None: ...


class AlertRequestHandler(Protocol):
    async def acknowledge(self, alert_id: str, *, by: str, at_ms: int, event_id: str) -> object: ...
    async def escalate(self, alert_id: str, *, by: str, at_ms: int, event_id: str) -> object: ...


@dataclass(slots=True)
class MessageService:
    settings: Settings
    store: FoundationStore
    engine: WorkflowEngine
    health: HealthRegistry
    bedside_handler: BedsideHandler | None = None
    m6_handler: M6Handler | None = None
    demo_handler: DemoControlHandler | None = None
    alert_request_handler: AlertRequestHandler | None = None

    async def handle(self, topic: str, payload: bytes) -> bool:
        try:
            message = parse_wire_message(
                topic, payload, max_bytes=self.settings.mqtt_max_payload_bytes
            )
        except ContractError as exc:
            await self.store.record_dead_letter(
                topic=topic,
                payload=payload,
                code=exc.code,
                detail=exc.detail,
            )
            self.health.increment("dead_letter")
            LOGGER.warning(
                "rejected MQTT message",
                extra={"error_code": exc.code},
            )
            return True

        correlation_id = correlation_id_for(message)
        idempotency_key = ingress_idempotency_key(message)
        created = await self.store.record_ingress(
            topic=topic,
            payload=payload,
            message=message,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        if not created and await self.store.ingress_is_processed(idempotency_key):
            self.health.increment("duplicate")
            return True

        if not created:
            self.health.increment("recovery_resume")

        self.health.increment("accepted")
        if isinstance(message, DemoControlMessage):
            try:
                if self.demo_handler is None:
                    raise ValueError("demo lifecycle is not enabled")
                await self.demo_handler.handle_control(message)
            except ValueError as exc:
                await self.store.record_dead_letter(
                    topic=topic, payload=payload, code="DEMO_CONTROL_REJECTED", detail=str(exc)
                )
                self.health.increment("demo_rejected")
            else:
                self.health.increment("demo_control_processed")
        elif isinstance(message, RequestMessage):
            if message.action in {"ack_alert", "escalate_alert"}:
                try:
                    if self.alert_request_handler is None:
                        raise ValueError("A1 alert request handler is unavailable")
                    operation = (
                        self.alert_request_handler.acknowledge
                        if message.action == "ack_alert"
                        else self.alert_request_handler.escalate
                    )
                    await operation(
                        message.target_id,
                        by=message.by,
                        at_ms=message.ts,
                        event_id=message.request_id,
                    )
                except (PermissionError, LookupError, ValueError) as exc:
                    await self.store.record_dead_letter(
                        topic=topic, payload=payload, code="ALERT_REQUEST_REJECTED", detail=str(exc)
                    )
                    self.health.increment("request_rejected")
                else:
                    self.health.increment("alert_request_processed")
            else:
                await self.store.append_audit(
                    correlation_id=message.request_id,
                    event_type="request.not_owned",
                    actor=message.by,
                    detail={"action": message.action, "target_id": message.target_id},
                )
        if self.m6_handler is not None and (
            isinstance(message, VitalsMessage)
            or (isinstance(message, ScoreMessage) and message.model in {"M3", "M5"})
        ):
            try:
                score = await self.m6_handler.handle_m6(message)
            except ValueError as exc:
                await self.store.record_dead_letter(
                    topic=topic, payload=payload, code="M6_CONTEXT_REJECTED", detail=str(exc)
                )
                self.health.increment("m6_rejected")
            else:
                if score is not None:
                    self.health.increment("m6_score_queued")
        if isinstance(message, VerdictMessage):
            await self.engine.run(message, thread_id=correlation_id)
            self.health.increment("workflow_completed")
        elif isinstance(message, BedsideCheckMessage) and self.bedside_handler is not None:
            try:
                await self.bedside_handler.handle_bedside(message)
            except PermissionError as exc:
                await self.store.record_dead_letter(
                    topic=topic,
                    payload=payload,
                    code="UNAUTHORIZED_BEDSIDE",
                    detail=str(exc),
                )
                self.health.increment("bedside_rejected")
            else:
                self.health.increment("bedside_processed")
        await self.store.mark_ingress_processed(idempotency_key)
        return True
