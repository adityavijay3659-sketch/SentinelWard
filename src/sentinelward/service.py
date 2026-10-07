from __future__ import annotations

import logging
from dataclasses import dataclass

from sentinelward.config import Settings
from sentinelward.contracts import (
    VerdictMessage,
    correlation_id_for,
    ingress_idempotency_key,
    parse_wire_message,
)
from sentinelward.errors import ContractError
from sentinelward.health import HealthRegistry
from sentinelward.ports import FoundationStore, WorkflowEngine

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class MessageService:
    settings: Settings
    store: FoundationStore
    engine: WorkflowEngine
    health: HealthRegistry

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
        if isinstance(message, VerdictMessage):
            await self.engine.run(message, thread_id=correlation_id)
            self.health.increment("workflow_completed")
        await self.store.mark_ingress_processed(idempotency_key)
        return True
