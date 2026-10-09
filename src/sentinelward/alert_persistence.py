from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sentinelward.alerts import (
    AlertRecord,
    CallbackTarget,
    DeliveryRecord,
    RosterSnapshot,
)


@dataclass(slots=True)
class InMemoryAlertStore:
    alerts: dict[str, AlertRecord] = field(default_factory=dict)
    callbacks: set[str] = field(default_factory=set)
    deliveries: dict[str, DeliveryRecord] = field(default_factory=dict)
    rosters: dict[str, RosterSnapshot] = field(default_factory=dict)
    callback_targets: dict[str, CallbackTarget] = field(default_factory=dict)

    async def get_active_alert(self, bed_id: str) -> AlertRecord | None:
        matches = [
            alert for alert in self.alerts.values() if alert.bed_id == bed_id and alert.active
        ]
        return max(matches, key=lambda item: item.created_ts) if matches else None

    async def get_alert(self, alert_id: str) -> AlertRecord | None:
        return self.alerts.get(alert_id)

    async def save_alert(self, alert: AlertRecord) -> None:
        self.alerts[alert.alert_id] = alert

    async def record_callback(self, event_id: str, alert_id: str) -> bool:
        del alert_id
        if event_id in self.callbacks:
            return False
        self.callbacks.add(event_id)
        return True

    async def save_delivery(self, delivery: DeliveryRecord) -> None:
        self.deliveries[delivery.delivery_key] = delivery

    async def list_deliveries(self, alert_id: str) -> list[DeliveryRecord]:
        return [delivery for delivery in self.deliveries.values() if delivery.alert_id == alert_id]

    async def get_cached_roster(self, bed_id: str, at_ms: int) -> RosterSnapshot | None:
        roster = self.rosters.get(bed_id)
        if roster is None or roster.valid_until < at_ms:
            return None
        return roster

    async def save_roster(self, roster: RosterSnapshot) -> None:
        self.rosters[roster.bed_id] = roster

    async def save_callback_target(self, target: CallbackTarget) -> None:
        self.callback_targets[target.token] = target

    async def get_callback_target(self, token: str) -> CallbackTarget | None:
        return self.callback_targets.get(token)


@dataclass(frozen=True, slots=True)
class PostgresAlertStore:
    database_url: str

    async def get_active_alert(self, bed_id: str) -> AlertRecord | None:
        query = """
            SELECT state FROM automation.alerts
            WHERE bed_id = %s AND active
            ORDER BY created_at DESC LIMIT 1
        """
        return await self._fetch_alert(query, (bed_id,))

    async def get_alert(self, alert_id: str) -> AlertRecord | None:
        return await self._fetch_alert(
            "SELECT state FROM automation.alerts WHERE alert_id = %s", (alert_id,)
        )

    async def save_alert(self, alert: AlertRecord) -> None:
        query = """
            INSERT INTO automation.alerts (
                alert_id, bed_id, active, state, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, to_timestamp(%s / 1000.0), to_timestamp(%s / 1000.0))
            ON CONFLICT (alert_id) DO UPDATE SET
                active = EXCLUDED.active,
                state = EXCLUDED.state,
                updated_at = EXCLUDED.updated_at
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute(
                query,
                (
                    alert.alert_id,
                    alert.bed_id,
                    alert.active,
                    Jsonb(alert.model_dump(mode="json")),
                    alert.created_ts,
                    alert.updated_ts,
                ),
            )

    async def record_callback(self, event_id: str, alert_id: str) -> bool:
        query = """
            INSERT INTO automation.alert_callbacks (event_id, alert_id, received_at)
            VALUES (%s, %s, now()) ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(query, (event_id, alert_id))
            return await cursor.fetchone() is not None

    async def save_delivery(self, delivery: DeliveryRecord) -> None:
        query = """
            INSERT INTO automation.alert_deliveries (
                delivery_key, alert_id, staff_id, status, state, updated_at
            ) VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (delivery_key) DO UPDATE SET
                status = EXCLUDED.status,
                state = EXCLUDED.state,
                updated_at = now()
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute(
                query,
                (
                    delivery.delivery_key,
                    delivery.alert_id,
                    delivery.staff_id,
                    delivery.status,
                    Jsonb(delivery.model_dump(mode="json")),
                ),
            )

    async def list_deliveries(self, alert_id: str) -> list[DeliveryRecord]:
        query = """
            SELECT state FROM automation.alert_deliveries
            WHERE alert_id = %s ORDER BY delivery_key
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(query, (alert_id,))
            rows = await cursor.fetchall()
        return [DeliveryRecord.model_validate(row[0]) for row in rows]

    async def get_cached_roster(self, bed_id: str, at_ms: int) -> RosterSnapshot | None:
        query = """
            SELECT state FROM automation.roster_snapshots
            WHERE bed_id = %s AND valid_until >= to_timestamp(%s / 1000.0)
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(query, (bed_id, at_ms))
            row = await cursor.fetchone()
        return RosterSnapshot.model_validate(row[0]) if row else None

    async def save_roster(self, roster: RosterSnapshot) -> None:
        query = """
            INSERT INTO automation.roster_snapshots (
                bed_id, assignment_version, valid_until, state, updated_at
            ) VALUES (%s, %s, to_timestamp(%s / 1000.0), %s, now())
            ON CONFLICT (bed_id) DO UPDATE SET
                assignment_version = EXCLUDED.assignment_version,
                valid_until = EXCLUDED.valid_until,
                state = EXCLUDED.state,
                updated_at = now()
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute(
                query,
                (
                    roster.bed_id,
                    roster.assignment_version,
                    roster.valid_until,
                    Jsonb(roster.model_dump(mode="json")),
                ),
            )

    async def save_callback_target(self, target: CallbackTarget) -> None:
        query = """
            INSERT INTO automation.alert_callback_tokens (
                token, alert_id, action, target, created_at
            ) VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (token) DO NOTHING
        """
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            await connection.execute(
                query,
                (
                    target.token,
                    target.alert_id,
                    target.action,
                    Jsonb(target.model_dump(mode="json")),
                ),
            )

    async def get_callback_target(self, token: str) -> CallbackTarget | None:
        query = "SELECT target FROM automation.alert_callback_tokens WHERE token = %s"
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(query, (token,))
            row = await cursor.fetchone()
        return CallbackTarget.model_validate(row[0]) if row else None

    async def _fetch_alert(self, query: str, params: tuple[Any, ...]) -> AlertRecord | None:
        async with await psycopg.AsyncConnection.connect(self.database_url) as connection:
            cursor = await connection.execute(query, params)
            row = await cursor.fetchone()
        return AlertRecord.model_validate(row[0]) if row else None
