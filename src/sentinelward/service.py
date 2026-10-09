from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from sentinelward.config import Settings
from sentinelward.contracts import (
    BedsideCheckMessage,
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


@dataclass(slots=True)
class MessageService:
    settings: Settings
    store: FoundationStore
    engine: WorkflowEngine
    health: HealthRegistry
    bedside_handler: BedsideHandler | None = None
    m6_handler: M6Handler | None = None

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
