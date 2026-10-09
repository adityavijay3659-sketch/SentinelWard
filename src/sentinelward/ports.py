from __future__ import annotations

from typing import Any, Protocol

from sentinelward.contracts import ActionRequest, ActionResult, VerdictMessage, WireMessage


class WorkflowEngine(Protocol):
    async def run(self, message: VerdictMessage, *, thread_id: str) -> object: ...


class FoundationStore(Protocol):
    async def record_ingress(
        self,
        *,
        topic: str,
        payload: bytes,
        message: WireMessage,
        idempotency_key: str,
        correlation_id: str,
    ) -> bool: ...

    async def ingress_is_processed(self, idempotency_key: str) -> bool: ...

    async def mark_ingress_processed(self, idempotency_key: str) -> None: ...

    async def record_dead_letter(
        self, *, topic: str, payload: bytes, code: str, detail: str
    ) -> None: ...

    async def reserve_action(self, request: ActionRequest) -> tuple[str, bool]: ...

    async def complete_action(self, result: ActionResult) -> None: ...

    async def append_audit(
        self,
        *,
        correlation_id: str,
        event_type: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None: ...

    async def enqueue_outbox(
        self,
        *,
        delivery_key: str,
        destination: str,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> bool: ...

    async def due_mqtt_outbox(self, limit: int = 100) -> list[dict[str, Any]]: ...

    async def mark_outbox_delivered(self, delivery_key: str) -> None: ...

    async def reschedule_outbox(
        self, delivery_key: str, *, error: str, delay_seconds: int
    ) -> None: ...

    async def ping(self) -> bool: ...


class ActionPort(Protocol):
    async def execute(self, request: ActionRequest, *, action_id: str) -> ActionResult: ...
