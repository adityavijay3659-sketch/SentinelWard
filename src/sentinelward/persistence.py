from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from sentinelward.contracts import (
    ActionRequest,
    ActionResult,
    WireMessage,
    payload_sha256,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class InMemoryStore:
    ingress: dict[str, dict[str, Any]] = field(default_factory=dict)
    dead_letters: list[dict[str, Any]] = field(default_factory=list)
    actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    audits: list[dict[str, Any]] = field(default_factory=list)
    outbox: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def record_ingress(
        self,
        *,
        topic: str,
        payload: bytes,
        message: WireMessage,
        idempotency_key: str,
        correlation_id: str,
    ) -> bool:
        if idempotency_key in self.ingress:
            return False
        self.ingress[idempotency_key] = {
            "topic": topic,
            "payload": message.model_dump(mode="json"),
            "payload_sha256": payload_sha256(payload),
            "correlation_id": correlation_id,
            "status": "accepted",
        }
        return True

    async def ingress_is_processed(self, idempotency_key: str) -> bool:
        return str(self.ingress[idempotency_key]["status"]) == "processed"

    async def mark_ingress_processed(self, idempotency_key: str) -> None:
        self.ingress[idempotency_key]["status"] = "processed"

    async def record_dead_letter(
        self, *, topic: str, payload: bytes, code: str, detail: str
    ) -> None:
        self.dead_letters.append(
            {
                "topic": topic,
                "payload_sha256": payload_sha256(payload),
                "payload_excerpt": payload[:2048].decode("utf-8", errors="replace"),
                "code": code,
                "detail": detail[:1000],
            }
        )

    async def reserve_action(self, request: ActionRequest) -> tuple[str, bool]:
        key = request.idempotency_key
        existing = self.actions.get(key)
        if existing is not None:
            return str(existing["action_id"]), False
        action_id = f"act_{uuid4().hex}"
        self.actions[key] = {
            "action_id": action_id,
            "status": "reserved",
            "request": request.model_dump(mode="json"),
        }
        return action_id, True

    async def complete_action(self, result: ActionResult) -> None:
        action = self.actions[result.idempotency_key]
        action["status"] = result.status
        action["result"] = result.model_dump(mode="json")

    async def append_audit(
        self,
        *,
        correlation_id: str,
        event_type: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        self.audits.append(
            {
                "correlation_id": correlation_id,
                "event_type": event_type,
                "actor": actor,
                "detail": detail,
            }
        )

    async def enqueue_outbox(
        self,
        *,
        delivery_key: str,
        destination: str,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> bool:
        if delivery_key in self.outbox:
            return False
        self.outbox[delivery_key] = {
            "destination": destination,
            "payload": payload,
            "correlation_id": correlation_id,
            "status": "pending",
        }
        return True

    async def ping(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class PostgresStore:
    database_url: str

    async def record_ingress(
        self,
        *,
        topic: str,
        payload: bytes,
        message: WireMessage,
        idempotency_key: str,
        correlation_id: str,
    ) -> bool:
        query = """
            INSERT INTO automation.ingress_events (
                ingress_id, topic, received_at, payload, payload_sha256,
                idempotency_key, correlation_id, status
            ) VALUES (%s, %s, now(), %s, %s, %s, %s, 'accepted')
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING ingress_id
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(
                query,
                (
                    uuid4(),
                    topic,
                    Jsonb(message.model_dump(mode="json")),
                    payload_sha256(payload),
                    idempotency_key,
                    correlation_id,
                ),
            )
            return await cursor.fetchone() is not None

    async def ingress_is_processed(self, idempotency_key: str) -> bool:
        query = "SELECT status FROM automation.ingress_events WHERE idempotency_key = %s"
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(query, (idempotency_key,))
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("ingress record disappeared before status check")
            return str(row[0]) == "processed"

    async def mark_ingress_processed(self, idempotency_key: str) -> None:
        query = """
            UPDATE automation.ingress_events
            SET status = 'processed'
            WHERE idempotency_key = %s AND status = 'accepted'
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute(query, (idempotency_key,))

    async def record_dead_letter(
        self, *, topic: str, payload: bytes, code: str, detail: str
    ) -> None:
        query = """
            INSERT INTO automation.dead_letters (
                dead_letter_id, topic, received_at, payload_sha256,
                payload_excerpt, error_code, error_detail
            ) VALUES (%s, %s, now(), %s, %s, %s, %s)
        """
        excerpt = payload[:2048].decode("utf-8", errors="replace")
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute(
                query,
                (uuid4(), topic, payload_sha256(payload), excerpt, code, detail[:1000]),
            )

    async def reserve_action(self, request: ActionRequest) -> tuple[str, bool]:
        action_id = f"act_{uuid4().hex}"
        query = """
            INSERT INTO automation.action_reservations (
                action_id, action_key, correlation_id, agent_id, action_name,
                target_id, status, request, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'reserved', %s, now(), now())
            ON CONFLICT (action_key) DO NOTHING
            RETURNING action_id
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(
                query,
                (
                    action_id,
                    request.idempotency_key,
                    request.correlation_id,
                    request.agent_id,
                    request.action,
                    request.target_id,
                    Jsonb(request.model_dump(mode="json")),
                ),
            )
            inserted = await cursor.fetchone()
            if inserted is not None:
                return str(inserted[0]), True
            cursor = await connection.execute(
                "SELECT action_id FROM automation.action_reservations WHERE action_key = %s",
                (request.idempotency_key,),
            )
            existing = await cursor.fetchone()
            if existing is None:
                raise RuntimeError("action reservation disappeared after uniqueness conflict")
            return str(existing[0]), False

    async def complete_action(self, result: ActionResult) -> None:
        query = """
            UPDATE automation.action_reservations
            SET status = %s, result = %s, updated_at = now()
            WHERE action_key = %s
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute(
                query,
                (result.status, Jsonb(result.model_dump(mode="json")), result.idempotency_key),
            )

    async def append_audit(
        self,
        *,
        correlation_id: str,
        event_type: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        query = """
            INSERT INTO automation.audit_events (
                audit_id, occurred_at, correlation_id, event_type, actor, detail
            ) VALUES (%s, now(), %s, %s, %s, %s)
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute(
                query, (uuid4(), correlation_id, event_type, actor, Jsonb(detail))
            )

    async def enqueue_outbox(
        self,
        *,
        delivery_key: str,
        destination: str,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> bool:
        query = """
            INSERT INTO automation.outbox_events (
                outbox_id, delivery_key, destination, payload, correlation_id,
                status, attempt_count, next_attempt_at, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, 'pending', 0, now(), now(), now())
            ON CONFLICT (delivery_key) DO NOTHING
            RETURNING outbox_id
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(
                query,
                (uuid4(), delivery_key, destination, Jsonb(payload), correlation_id),
            )
            return await cursor.fetchone() is not None

    async def ping(self) -> bool:
        try:
            async with await psycopg.AsyncConnection.connect(
                self.database_url, connect_timeout=3
            ) as connection:
                cursor = await connection.execute("SELECT 1")
                row = await cursor.fetchone()
                return row == (1,)
        except psycopg.Error:
            return False


def json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
