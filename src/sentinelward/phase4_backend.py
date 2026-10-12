"""Explicit local backend reference; these are not the deployed teammate APIs."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from sentinelward.alerts import DeliveryRecord, ProviderMessage, RosterSnapshot
from sentinelward.contracts import AlertMessage
from sentinelward.phase4_state import AgentRepository


@dataclass
class LocalProjection:
    repository: AgentRepository

    async def set_untrusted(self, bed_id: str, latest: dict[str, Any]) -> None:
        async with self.repository.transaction() as unit:
            unit.state.bed_projections[bed_id] = {
                "state": "untrusted",
                "latest": copy.deepcopy(latest),
                "run_id": unit.state.run_id,
            }

    async def reconnecting(self, bed_id: str) -> None:
        async with self.repository.transaction() as unit:
            projection = unit.state.bed_projections.setdefault(bed_id, {})
            projection["state"] = "reconnecting"

    async def replace(self, device_id: str, lease_ids: list[str]) -> None:
        async with self.repository.transaction() as unit:
            unit.state.effective_watches[device_id] = list(lease_ids)


class LocalClinicalReference:
    """Local screen/roster reference; it never pretends to deliver Telegram."""

    async def get_roster(self, bed_id: str) -> RosterSnapshot:
        return RosterSnapshot(
            v=1,
            bed_id=bed_id,
            assigned_nurse="staff:priya",
            next_nurse="staff:ravi",
            unit_nurses=["staff:priya", "staff:ravi"],
            on_call_doctor="staff:doctor",
            assignment_version="local-test-1",
            valid_until=253_402_300_799_999,
        )

    async def get_waveform_png(self, bed_id: str, end_ts: int) -> bytes | None:
        return None

    async def send(
        self, alert: AlertMessage, staff_id: str, *, waveform_png: bytes | None
    ) -> ProviderMessage:
        raise ConnectionError("Telegram backup unavailable in isolated local profile")

    async def edit_acknowledged(self, delivery: DeliveryRecord, *, by: str, at_ms: int) -> None:
        raise ConnectionError("No local Telegram delivery exists")

    async def edit_active(self, delivery: DeliveryRecord, alert: AlertMessage) -> None:
        raise ConnectionError("No local Telegram delivery exists")
