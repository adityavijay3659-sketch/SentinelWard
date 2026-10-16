"""Durable agent orchestration; deployed automatic containment is opt-in."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sentinelward.contracts import (
    ActionMessage,
    AlertMessage,
    DemoControlMessage,
    DemoSourceEnd,
    RecordMessage,
    RequestMessage,
    Verdict,
    VerdictMessage,
    VitalsMessage,
)
from sentinelward.demo_lifecycle import SOURCE_END_SECONDS, SOURCE_JOIN_SECONDS
from sentinelward.phase4_adapters import BrokerControl, EvidenceFiles, ProjectionPort, WatchPort
from sentinelward.phase4_state import (
    AgentRepository,
    AgentState,
    AgentTransaction,
    Authorization,
    ContainmentPolicy,
    Device,
    identity,
)


@dataclass
class Phase4Coordinator:
    repository: AgentRepository
    inventory: dict[str, Device]
    broker: BrokerControl
    projection: ProjectionPort
    watch: WatchPort
    evidence: EvidenceFiles
    policy: ContainmentPolicy | None = None
    isolated_lab: bool = False
    clock_ms: Callable[[], int] = field(default=lambda: time.time_ns() // 1_000_000)
    reset_alerts: Callable[[int, list[str]], Awaitable[None]] | None = None
    bind_alert_run: Callable[[str | None], None] | None = None
    after_control: Callable[[DemoControlMessage], Awaitable[None]] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    lifecycle_gate: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        if self.isolated_lab and any(not device.lab_owned for device in self.inventory.values()):
            raise ValueError("isolated coordinator cannot control a non-lab device")
        if len({d.bed_id for d in self.inventory.values()}) != len(self.inventory):
            raise ValueError("bed/device mapping must be unique")

    def _device(self, bed_id: str) -> Device:
        matches = [device for device in self.inventory.values() if device.bed_id == bed_id]
        if len(matches) != 1:
            raise ValueError("bed has no unique inventory device")
        return matches[0]

    def _validate(self, state: AgentState, bed_id: str, ts: int, window: int | None = None) -> None:
        device = self._device(bed_id)
        if not state.active or not state.run_id:
            raise ValueError("agent run is inactive")
        join = SOURCE_JOIN_SECONDS.get(bed_id, 0)
        first = state.start_ts + max(0, join - state.start_at_s) * 1000
        end = (
            state.start_ts + max(0, SOURCE_END_SECONDS.get(bed_id, 1200) - state.start_at_s) * 1000
        )
        if ts < first or (window is not None and window < first):
            raise ValueError("stale agent observation")
        if ts >= end or bed_id in state.offline:
            raise ValueError("recording is offline")
        if ts > self.clock_ms() + 5000:
            raise ValueError("observation is in the future")
        if not device.device_id:
            raise ValueError("missing device")

    async def validate_verdict(self, message: VerdictMessage) -> None:
        async with self.repository.transaction() as unit:
            self._validate(unit.state, message.bed_id, message.ts, message.window_start)

    async def handle_control(self, command: DemoControlMessage) -> None:
        async with self.lifecycle_gate:
            await self._handle_control(command)

    async def control_with(
        self, command: DemoControlMessage, first: Callable[[DemoControlMessage], Awaitable[None]]
    ) -> None:
        async with self.lifecycle_gate:
            await first(command)
            await self._handle_control(command)

    async def _handle_control(self, command: DemoControlMessage) -> None:
        async with self._lock:
            digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
            async with self.repository.transaction() as unit:
                prior = copy.deepcopy(unit.state)
                if prior.control_digest == digest:
                    if self.after_control is not None:
                        await self.after_control(command)
                    return
                if command.ts <= prior.control_ts:
                    raise ValueError("stale agent control")
                if command.cmd == "run" and command.run_id in prior.used_runs:
                    raise ValueError("agent run identity reused")
                if command.cmd == "reset" and prior.run_id not in {None, command.run_id}:
                    raise ValueError("wrong agent reset identity")
                if command.cmd == "run" and command.ts <= max(
                    prior.highwater.values(), default=prior.start_ts - 1
                ):
                    raise ValueError("new agent run precedes prior observations")
            # Stop old active timers before enabling the new namespace. On failure, retry control.
            if self.bind_alert_run is not None:
                self.bind_alert_run(prior.run_id)
            if prior.run_id and self.reset_alerts is not None:
                await self.reset_alerts(prior.start_ts, [d.bed_id for d in self.inventory.values()])
            if command.cmd == "run" and self.isolated_lab:
                for device in self.inventory.values():
                    if device.lab_owned and await self.broker.disabled(device):

                        async def restore(d: Device = device) -> None:
                            if await self.broker.disabled(d):
                                await self.broker.clean_session(d)
                                await self.broker.enable(d)

                        restored = await self._effect(
                            f"lab-restore:{command.run_id}:{device.device_id}",
                            "A2",
                            "enable_client",
                            device,
                            restore,
                        )
                        if restored["status"] != "ok":
                            raise RuntimeError(
                                "lab account restoration incomplete; control retry required"
                            )
            # Watches are replaced rather than incremented, so crash retries are safe.
            for device_id in self.inventory:
                await self.watch.replace(device_id, [])
            async with self.repository.transaction() as unit:
                state = unit.state
                unit.retire_run = prior.run_id
                for effect in state.effects.values():
                    if effect.get("run_id") == prior.run_id and effect["status"] in {
                        "pending",
                        "unknown",
                    }:
                        effect["status"] = "unknown"
                        effect["retired"] = True
                state.active = command.cmd == "run"
                state.run_id = command.run_id
                state.start_ts = ((command.ts + 999) // 1000) * 1000
                state.start_at_s = command.start_at_s
                state.control_ts, state.control_digest = command.ts, digest
                if command.cmd == "run":
                    state.used_runs.append(command.run_id)
                state.highwater.clear()
                state.offline.clear()
                state.latest.clear()
                state.last_trusted.clear()
                state.untrusted.clear()
                state.loose_active.clear()
                state.loose_starts.clear()
                state.drift_active.clear()
                state.incident_by_device.clear()
                state.authorizations.clear()
                state.watches.clear()
                state.buffers.clear()
                state.ticket_highwater.clear()
                state.bed_projections.clear()
                state.effective_watches.clear()
                state.reconnect_ts.clear()
                state.active_containment.clear()
                unit.audits.append(("phase4.control", "backend", command.model_dump(mode="json")))
            if self.bind_alert_run is not None:
                self.bind_alert_run(command.run_id if command.cmd == "run" else None)
            if self.after_control is not None:
                await self.after_control(command)

    async def observe(self, message: VitalsMessage | VerdictMessage) -> None:
        async with self._lock, self.repository.transaction() as unit:
            state = unit.state
            self._validate(state, message.bed_id, message.ts)
            kind = "vitals" if isinstance(message, VitalsMessage) else "verdict"
            row = {"kind": kind, "ts": message.ts, "body": message.model_dump(mode="json")}
            buffer = state.buffers.setdefault(message.bed_id, [])
            if row not in buffer:
                buffer.append(row)
                buffer.append({"kind": "mqtt_observation", "ts": message.ts, "body": row["body"]})
            cutoff = message.ts - 600_000
            state.buffers[message.bed_id] = [r for r in buffer if r["ts"] >= cutoff][-2400:]
            if isinstance(message, VitalsMessage):
                device = self._device(message.bed_id)
                if device.device_id != message.device_id:
                    raise ValueError("frame/inventory device mismatch")
                latest = state.latest.get(message.bed_id)
                if latest is None or latest["ts"] < message.ts:
                    reading = {
                        "hr": message.hr,
                        "spo2": message.spo2,
                        "rr": message.rr,
                        "bp": message.nibp.model_dump(mode="json") if message.nibp else None,
                        "ts": message.ts,
                    }
                    state.latest[message.bed_id] = reading
                    if message.bed_id not in state.untrusted:
                        state.last_trusted[message.bed_id] = copy.deepcopy(reading)

    async def source_end(self, message: DemoSourceEnd) -> None:
        async with self._lock, self.repository.transaction() as unit:
            if message.run_id != unit.state.run_id or not unit.state.active:
                raise ValueError("stale source completion")
            if self._device(message.bed_id).device_id != message.device_id:
                raise ValueError("source identity mismatch")
            if message.ts < unit.state.start_ts:
                raise ValueError("source completion precedes run")
            unit.state.offline.setdefault(message.bed_id, message.ts)
            unit.state.bed_projections[message.bed_id] = {
                "state": "offline",
                "offline_since": unit.state.offline[message.bed_id],
                "latest": copy.deepcopy(unit.state.latest.get(message.bed_id, {})),
                "run_id": unit.state.run_id,
            }

    @staticmethod
    def _record(
        unit: AgentTransaction,
        kind: Literal["incident", "ticket"],
        record_id: str,
        data: dict[str, Any],
        ts: int,
    ) -> None:
        record = RecordMessage(
            v=1,
            type="record",
            ts=ts,
            kind=kind,
            record_id=record_id,
            by="A3" if kind == "incident" else "A6",
            data=copy.deepcopy(data),
        )
        unit.publish("ward/record", record.model_dump(mode="json"))

    @staticmethod
    def _action(unit: AgentTransaction, effect: dict[str, Any], ts: int) -> None:
        message = ActionMessage(
            v=1,
            type="action",
            action_id=effect["action_id"],
            ts=ts,
            by=effect["agent"],
            action=effect["action"],
            bed_id=effect.get("bed_id"),
            device_id=effect.get("device_id"),
            detail=effect.get("detail", "")[:240],
            undo_id=effect["action_id"] if effect.get("reversible", False) else None,
            undoes=effect.get("undoes"),
            approved_by=effect.get("approved_by"),
            result=effect["status"],
        )
        body = message.model_dump(mode="json")
        unit.publish("ward/action", body)
        unit.audits.append(("phase4.action", effect["agent"], body))
        if effect.get("bed_id"):
            unit.state.buffers.setdefault(effect["bed_id"], []).append(
                {"kind": "action", "ts": ts, "body": body}
            )
        if effect["agent"] != "A3":
            for incident in unit.state.incidents.values():
                if incident["run_id"] == unit.state.run_id and incident["bed_id"] == effect.get(
                    "bed_id"
                ):
                    row = {"ts": ts, "kind": "action", "body": body}
                    if row not in incident["timeline"]:
                        incident["timeline"].append(row)
                        incident["revision"] += 1

    async def _effect(
        self,
        key: str,
        agent: str,
        action: str,
        device: Device,
        execute: Callable[[], Awaitable[None]],
        *,
        approved_by: str | None = None,
        undoes: str | None = None,
    ) -> dict[str, Any]:
        async with self.repository.transaction() as unit:
            old = unit.state.effects.get(key)
            if old and (old["status"] == "ok" or old.get("retired")):
                return copy.deepcopy(old)
            effect = old or {
                "action_id": "act_" + identity(key),
                "agent": agent,
                "action": action,
                "run_id": unit.state.run_id,
                "device_id": device.device_id,
                "bed_id": device.bed_id,
                "approved_by": approved_by,
                "undoes": undoes,
                "reversible": action == "disable_client" and not key.endswith(":session"),
            }
            effect.update(status="pending", detail="Effect reserved; confirmation pending")
            unit.state.effects[key] = effect
            self._action(unit, effect, self.clock_ms())
        try:
            await execute()
        except (TimeoutError, ConnectionError, OSError):
            status, detail = "unknown", "External effect uncertain; reconciliation required"
        except Exception as exc:
            status, detail = (
                "failed",
                f"Adapter rejected/failed ({type(exc).__name__}); inspect adapter health",
            )
        else:
            status, detail = "ok", f"{action} confirmed"
        async with self.repository.transaction() as unit:
            effect = unit.state.effects[key]
            effect.update(status=status, detail=detail)
            self._action(unit, effect, self.clock_ms())
            return copy.deepcopy(effect)

    async def _contain(self, device: Device, cause: str, *, approved_by: str | None = None) -> None:
        async with self.repository.transaction() as unit:
            run = str(unit.state.run_id)
        key = f"{run}:contain:{device.device_id}:{cause}"
        async with self.repository.transaction() as unit:
            original = unit.state.effects.get(key)
            if original and original["action_id"] in unit.state.undo_links:
                return  # IT undo is not overridden by the same unresolved incident.

        async def disable() -> None:
            if not await self.broker.disabled(device):
                await self.broker.disable(device)

        result = await self._effect(
            key, "A2", "disable_client", device, disable, approved_by=approved_by
        )
        if result["status"] != "ok":
            return
        async with self.repository.transaction() as unit:
            unit.state.active_containment[device.device_id] = result["action_id"]
        # Cleanup and projection are separately journalled and independently recoverable.
        cleanup = await self._effect(
            f"{key}:session",
            "A2",
            "disable_client",
            device,
            lambda: self.broker.clean_session(device),
            approved_by=approved_by,
        )
        async with self.repository.transaction() as unit:
            reading = copy.deepcopy(unit.state.last_trusted.get(device.bed_id, {}))
            if device.bed_id not in unit.state.untrusted:
                unit.state.untrusted.append(device.bed_id)
        projection = await self._effect(
            f"{key}:projection",
            "A2",
            "set_bed_untrusted",
            device,
            lambda: self.projection.set_untrusted(device.bed_id, reading),
        )
        if cleanup["status"] == projection["status"] == "ok":

            async def lookup() -> None:
                # Inventory is explicit validated configuration, not a derived client ID.
                if device.device_id not in self.inventory:
                    raise LookupError("device inventory disappeared")

            await self._effect(f"{key}:inventory", "A4", "list_devices", device, lookup)
            async with self.repository.transaction() as unit:
                lease_id = "watch_" + identity(run, device.device_id, cause)
                if lease_id not in unit.state.watches:
                    unit.state.watches[lease_id] = {
                        "id": lease_id,
                        "origin": device.device_id,
                        "run_id": run,
                        "expires_ts": self.clock_ms() + 3_600_000,
                        "devices": [
                            d.device_id
                            for d in self.inventory.values()
                            if d.model == device.model and d.device_id != device.device_id
                        ],
                    }
            await self._apply_watches()

    async def _evidence(self, message: VerdictMessage, device: Device) -> None:
        async with self.repository.transaction() as unit:
            state = unit.state
            incident_id = state.incident_by_device.get(device.device_id)
            if incident_id is None:
                incident_id = "inc_" + identity(
                    str(state.run_id), device.device_id, str(message.window_start)
                )
                state.incident_by_device[device.device_id] = incident_id
                state.incidents[incident_id] = {
                    "run_id": state.run_id,
                    "bed_id": device.bed_id,
                    "device_id": device.device_id,
                    "ts": message.ts,
                    "status": "pending",
                    "evidence": [],
                    "revision": 0,
                    "snapshot": copy.deepcopy(state.buffers.get(message.bed_id, [])),
                    "timeline": [],
                    "pcap_available": False,
                }
            incident = copy.deepcopy(state.incidents[incident_id])

        async def freeze() -> None:
            artifacts = await asyncio.to_thread(
                self.evidence.freeze, incident_id, incident["snapshot"]
            )
            if not await asyncio.to_thread(self.evidence.verify, artifacts):
                raise ValueError("evidence verification failed")
            async with self.repository.transaction() as unit:
                current = unit.state.incidents[incident_id]
                current["evidence"] = artifacts
                current["status"] = "verified_available_context"
                current["missing_context"] = [a["kind"] for a in artifacts if not a["available"]]
                if current["missing_context"]:
                    current["status"] = "incomplete_context_verified"

        await self._effect(f"{incident_id}:snapshot", "A3", "snapshot_files", device, freeze)

        async def check_hashes() -> None:
            async with self.repository.transaction() as unit:
                artifacts = copy.deepcopy(unit.state.incidents[incident_id]["evidence"])
            if not artifacts or not await asyncio.to_thread(self.evidence.verify, artifacts):
                raise ValueError("evidence integrity unavailable or invalid")

        async with self.repository.transaction() as unit:
            hash_key = f"{incident_id}:hash"
            artifacts = unit.state.incidents[incident_id]["evidence"]
            if artifacts and not self.evidence.verify(artifacts) and hash_key in unit.state.effects:
                unit.state.effects[hash_key]["status"] = "unknown"
        hashed = await self._effect(hash_key, "A3", "hash_file", device, check_hashes)
        async with self.repository.transaction() as unit:
            incident = unit.state.incidents[incident_id]
            if hashed["status"] != "ok":
                incident["status"] = "incomplete_integrity"
            event = {"ts": message.ts, "kind": "verdict", "verdict": message.verdict.value}
            if event not in incident["timeline"]:
                incident["timeline"].append(event)
                incident["timeline"].sort(key=lambda row: row["ts"])
                incident["revision"] += 1
                data = {k: v for k, v in incident.items() if k != "snapshot"}
                self._record(unit, "incident", incident_id, data, message.ts)

    async def _tickets(self, message: VerdictMessage, device: Device) -> None:
        async with self.repository.transaction() as unit:
            state = unit.state
            if message.window_start <= state.ticket_highwater.get(message.bed_id, -1):
                return
            state.ticket_highwater[message.bed_id] = message.window_start
            distinct = False
            if message.verdict == Verdict.NORMAL:
                for collection in (state.loose_active, state.drift_active):
                    if device.device_id in collection:
                        collection.remove(device.device_id)
                state.incident_by_device.pop(device.device_id, None)
                latest = state.latest.get(message.bed_id)
                reconnected = state.reconnect_ts.get(message.bed_id)
                if latest and reconnected is not None and latest["ts"] > reconnected:
                    if message.bed_id in state.untrusted:
                        state.untrusted.remove(message.bed_id)
                    state.last_trusted[message.bed_id] = copy.deepcopy(latest)
                    state.bed_projections[message.bed_id] = {
                        "state": "live",
                        "latest": copy.deepcopy(latest),
                        "run_id": state.run_id,
                    }
                return
            kind = message.verdict.value
            if (
                message.verdict == Verdict.LOOSE_SENSOR
                and device.device_id not in state.loose_active
            ):
                state.loose_active.append(device.device_id)
                state.loose_starts.setdefault(device.device_id, []).append(message.ts)
                distinct = True
            elif message.verdict == Verdict.DRIFTING and device.device_id not in state.drift_active:
                state.drift_active.append(device.device_id)
                distinct = True
            if distinct:
                state.fault_history.append(
                    {
                        "run_id": state.run_id,
                        "device_id": device.device_id,
                        "ts": message.ts,
                        "kind": kind,
                    }
                )
            starts = [
                t
                for t in state.loose_starts.get(device.device_id, [])
                if message.ts - 1_800_000 < t <= message.ts
            ]
            eligible = message.verdict == Verdict.DRIFTING or (
                message.verdict == Verdict.LOOSE_SENSOR and len(starts) >= 3
            )
            if not eligible:
                return
            existing = next(
                (
                    (key, ticket)
                    for key, ticket in state.tickets.items()
                    if ticket["device_id"] == device.device_id
                    and ticket["status"] != "done"
                    and ticket["run_id"] == state.run_id
                ),
                None,
            )
            if existing is None and not distinct:
                # A closed ticket cannot be reopened by continued old observations.
                return
            if existing is None:
                ticket_id = "tk_" + identity(str(state.run_id), device.device_id, str(message.ts))
                ticket = {
                    "run_id": state.run_id,
                    "device_id": device.device_id,
                    "bed_id": device.bed_id,
                    "affected_beds": [device.bed_id],
                    "status": "new",
                    "fault_types": [],
                    "first_ts": message.ts,
                    "last_ts": message.ts,
                    "revision": 0,
                    "destination": "biomedical_engineering",
                    "note": "",
                }
                state.tickets[ticket_id] = ticket
                action = "open_ticket"
                before_ticket = None
            else:
                ticket_id, ticket = existing
                before_ticket = copy.deepcopy(ticket)
                action = "update_ticket"
            if kind not in ticket["fault_types"]:
                ticket["fault_types"].append(kind)
            ticket["last_ts"] = message.ts
            ticket["revision"] += 1
            ticket["loose_episodes_30m"] = len(starts)
            ticket["issues_30d"] = len(
                [
                    h
                    for h in state.fault_history
                    if h["device_id"] == device.device_id
                    and h["run_id"] == state.run_id
                    and message.ts - 2_592_000_000 < h["ts"] <= message.ts
                ]
            )
            ticket["suggestion"] = (
                "Re-level and re-zero the transducer; take a cuff reading"
                if "DRIFTING" in ticket["fault_types"]
                else "Check and refit the sensor; request biomed review"
            )
            self._record(unit, "ticket", ticket_id, ticket, message.ts)
            effect = {
                "action_id": "act_" + identity(ticket_id, str(ticket["revision"])),
                "agent": "A6",
                "action": action,
                "status": "ok",
                "bed_id": device.bed_id,
                "device_id": device.device_id,
                "detail": f"Biomed ticket {ticket_id} {ticket['status']}",
                "run_id": state.run_id,
                "reversible": True,
                "ticket_id": ticket_id,
                "ticket_revision": ticket["revision"],
                "ticket_before": before_ticket,
            }
            state.effects[f"ticket:{ticket_id}:{ticket['revision']}"] = effect
            self._action(unit, effect, message.ts)

    async def handle_verdict(self, message: VerdictMessage) -> list[dict[str, Any]]:
        await self.observe(message)
        async with self._lock:
            async with self.repository.transaction() as unit:
                state = unit.state
                self._validate(state, message.bed_id, message.ts, message.window_start)
                previous = state.highwater.get(message.bed_id, -1)
                if message.window_start < previous:
                    return []
                state.highwater[message.bed_id] = message.window_start
            device = self._device(message.bed_id)
            if message.verdict in {Verdict.TAMPERING, Verdict.BOTH, Verdict.DEVICE_ATTACK}:
                await self._evidence(message, device)
            if (
                message.verdict in {Verdict.TAMPERING, Verdict.BOTH}
                and self.policy is not None
                and (self.isolated_lab or self.policy.approved)
                and self.policy.accepts(message.confidence)
            ):
                async with self.repository.transaction() as unit:
                    cause = unit.state.incident_by_device[device.device_id]
                await self._contain(device, cause)
            await self._tickets(message, device)
            async with self.repository.transaction() as unit:
                return [
                    copy.deepcopy(effect)
                    for effect in unit.state.effects.values()
                    if effect.get("run_id") == unit.state.run_id
                    and effect.get("device_id") == device.device_id
                ]

    async def _apply_watches(self) -> None:
        async with self.repository.transaction() as unit:
            leases = copy.deepcopy(unit.state.watches)
            run_id = str(unit.state.run_id)
            unit.state.watch_generation += 1
            generation = unit.state.watch_generation
        for device in self.inventory.values():
            active = sorted(
                key
                for key, lease in leases.items()
                if lease["expires_ts"] > self.clock_ms() and device.device_id in lease["devices"]
            )
            async with self.repository.transaction() as unit:
                if unit.state.effective_watches.get(device.device_id, []) == active:
                    continue
                added = [
                    lease
                    for lease in active
                    if lease not in unit.state.effective_watches.get(device.device_id, [])
                ]
            key = f"{run_id}:watch:{device.device_id}:{generation}:" + identity(*active)

            async def replace(
                device_id: str = device.device_id, leases: list[str] = active
            ) -> None:
                await self.watch.replace(device_id, leases)
                async with self.repository.transaction() as unit:
                    unit.state.effective_watches[device_id] = list(leases)

            await self._effect(
                key,
                "A4",
                "set_watch_level",
                device,
                replace,
            )
            async with self.repository.transaction() as unit:
                unit.state.effects[key].update(reversible=bool(added), added_leases=added)
                if added and unit.state.effects[key]["status"] == "ok":
                    self._action(unit, unit.state.effects[key], self.clock_ms())

    async def advance(self) -> None:
        async with self.lifecycle_gate, self._lock:
            async with self.repository.transaction() as unit:
                changed = any(
                    lease["expires_ts"] <= self.clock_ms() for lease in unit.state.watches.values()
                )
                unit.state.watches = {
                    k: v for k, v in unit.state.watches.items() if v["expires_ts"] > self.clock_ms()
                }
                if unit.state.active:
                    for device in self.inventory.values():
                        end = (
                            unit.state.start_ts
                            + max(
                                0,
                                SOURCE_END_SECONDS.get(device.bed_id, 1200) - unit.state.start_at_s,
                            )
                            * 1000
                        )
                        if self.clock_ms() >= end:
                            unit.state.offline.setdefault(device.bed_id, end)
                            unit.state.bed_projections[device.bed_id] = {
                                "state": "offline",
                                "offline_since": unit.state.offline[device.bed_id],
                                "latest": copy.deepcopy(unit.state.latest.get(device.bed_id, {})),
                                "run_id": unit.state.run_id,
                            }
                    if (
                        self.clock_ms()
                        >= unit.state.start_ts + (1200 - unit.state.start_at_s) * 1000
                    ):
                        unit.state.active = False
            if changed:
                await self._apply_watches()

    async def register_authorization(self, authorization: Authorization) -> None:
        async with self._lock, self.repository.transaction() as unit:
            if authorization.run_id != unit.state.run_id or not unit.state.active:
                raise ValueError("authorization belongs to inactive run")
            existing = unit.state.authorizations.get(authorization.request_id)
            body = authorization.model_dump(mode="json")
            if existing is not None and existing != body:
                raise ValueError("request authorization identity cannot be replaced")
            unit.state.authorizations[authorization.request_id] = body

    async def handle_request(self, message: RequestMessage) -> None:
        async with self._lock:
            async with self.repository.transaction() as unit:
                state = unit.state
                raw = state.authorizations.get(message.request_id)
                if raw is None:
                    raise PermissionError("trusted request registration missing")
                authorization = Authorization.model_validate(raw)
                if (
                    not state.active
                    or authorization.run_id != state.run_id
                    or authorization.by != message.by
                    or authorization.role != "it"
                    or authorization.action != message.action
                    or authorization.target_id != message.target_id
                    or authorization.expires_ts < self.clock_ms()
                    or message.ts < state.start_ts
                    or message.ts > self.clock_ms() + 5000
                ):
                    raise PermissionError("request identity, role, expiry or run mismatch")
                if message.action == "isolate_device":
                    device = self.inventory.get(message.target_id)
                    if device is None:
                        raise LookupError("unknown device")
                    original = None
                elif message.action == "undo_action":
                    original = next(
                        (
                            copy.deepcopy(e)
                            for e in state.effects.values()
                            if e["action_id"] == message.target_id
                            and e["agent"] in {"A2", "A4", "A6"}
                            and e["status"] == "ok"
                            and e["run_id"] == state.run_id
                            and e.get("reversible", False)
                        ),
                        None,
                    )
                    if original is None:
                        raise LookupError("original reversible action not found in current run")
                    device = self.inventory[original["device_id"]]
                    linked = state.undo_links.get(message.target_id)
                    if linked and any(
                        e["action_id"] == linked and e["status"] == "ok"
                        for e in state.effects.values()
                    ):
                        return
                    if (
                        original["agent"] == "A2"
                        and state.active_containment.get(device.device_id) != message.target_id
                    ):
                        raise ValueError(
                            "a newer containment owns this device; old undo is rejected"
                        )
                else:
                    raise ValueError("request action is not Phase 4 owned")
                if message.bed_id is not None and message.bed_id != device.bed_id:
                    raise PermissionError("request bed/device mismatch")
            if original is None:
                await self._contain(device, f"request:{message.request_id}", approved_by=message.by)
                return

            if original["agent"] in {"A4", "A6"}:

                async def compensate() -> None:
                    async with self.repository.transaction() as unit:
                        state = unit.state
                        if message.target_id in state.undo_links:
                            return
                        if original["agent"] == "A6":
                            ticket_id = original["ticket_id"]
                            ticket = state.tickets[ticket_id]
                            if ticket["revision"] != original["ticket_revision"]:
                                raise ValueError(
                                    "ticket changed since action; undo would overwrite later work"
                                )
                            revision = ticket["revision"] + 1
                            previous = original["ticket_before"]
                            if previous is None:
                                ticket.update(
                                    status="done",
                                    resolution="cancelled_by_undo",
                                    note="Cancelled by authorized undo; no repair claimed",
                                )
                            else:
                                state.tickets[ticket_id] = ticket = copy.deepcopy(previous)
                            ticket["revision"] = revision
                            self._record(unit, "ticket", ticket_id, ticket, self.clock_ms())
                        else:
                            for lease_id in original.get("added_leases", []):
                                lease = state.watches.get(lease_id)
                                if lease and device.device_id in lease["devices"]:
                                    lease["devices"].remove(device.device_id)
                        if original["agent"] == "A6":
                            state.undo_links[message.target_id] = "act_" + identity(
                                f"undo:{message.target_id}"
                            )
                    if original["agent"] == "A4":
                        async with self.repository.transaction() as unit:
                            active = sorted(
                                key
                                for key, lease in unit.state.watches.items()
                                if device.device_id in lease["devices"]
                                and lease["expires_ts"] > self.clock_ms()
                            )
                        await self.watch.replace(device.device_id, active)
                        async with self.repository.transaction() as unit:
                            unit.state.effective_watches[device.device_id] = active
                            unit.state.undo_links[message.target_id] = "act_" + identity(
                                f"undo:{message.target_id}"
                            )

                await self._effect(
                    f"undo:{message.target_id}",
                    original["agent"],
                    "update_ticket" if original["agent"] == "A6" else "set_watch_level",
                    device,
                    compensate,
                    approved_by=message.by,
                    undoes=message.target_id,
                )
                return

            async def enable() -> None:
                if await self.broker.disabled(device):
                    await self.broker.enable(device)
                await self.projection.reconnecting(device.bed_id)

            result = await self._effect(
                f"undo:{message.target_id}",
                "A2",
                "enable_client",
                device,
                enable,
                approved_by=message.by,
                undoes=message.target_id,
            )
            if result["status"] == "ok":
                async with self.repository.transaction() as unit:
                    unit.state.undo_links[message.target_id] = result["action_id"]
                    unit.state.reconnect_ts[device.bed_id] = self.clock_ms()
                    unit.state.active_containment.pop(device.device_id, None)

    async def set_ticket_status(
        self,
        ticket_id: str,
        *,
        authorization: Authorization,
        status: Literal["new", "in_progress", "done"],
        expected_revision: int,
        note: str,
    ) -> dict[str, Any]:
        async with self._lock, self.repository.transaction() as unit:
            ticket = unit.state.tickets.get(ticket_id)
            if ticket is None:
                raise LookupError("unknown ticket")
            if (
                authorization.role != "biomed"
                or authorization.target_id != ticket_id
                or authorization.action != "ticket_status"
                or authorization.expires_ts < self.clock_ms()
                or authorization.run_id != unit.state.run_id
                or ticket["run_id"] != unit.state.run_id
                or not unit.state.active
            ):
                raise PermissionError("biomed authorization missing")
            if ticket["revision"] != expected_revision:
                raise ValueError("stale ticket revision")
            ticket.update(
                status=status,
                revision=expected_revision + 1,
                note=note[:240],
                updated_by=authorization.by,
            )
            self._record(unit, "ticket", ticket_id, ticket, self.clock_ms())
            unit.audits.append(
                (
                    "phase4.ticket_status",
                    authorization.by,
                    {"ticket_id": ticket_id, "status": status},
                )
            )
            return copy.deepcopy(ticket)

    async def snapshot(self) -> dict[str, Any]:
        async with self.repository.transaction() as unit:
            return copy.deepcopy(asdict(unit.state))

    async def observe_output(self, message: ActionMessage | AlertMessage) -> None:
        async with self._lock, self.repository.transaction() as unit:
            state = unit.state
            if (
                not state.active
                or message.ts < state.start_ts
                or message.ts > self.clock_ms() + 5000
            ):
                return
            if isinstance(message, ActionMessage) and message.by == "A3":
                return  # Timeline-writer events must not recursively trigger themselves.
            body = message.model_dump(mode="json")
            row = {"ts": message.ts, "kind": message.type, "body": body}
            for incident in state.incidents.values():
                if (
                    incident["run_id"] == state.run_id
                    and incident["bed_id"] == message.bed_id
                    and row not in incident["timeline"]
                ):
                    incident["timeline"].append(row)
                    incident["revision"] += 1

    async def flush_timelines(self) -> None:
        async with self._lock:
            async with self.repository.transaction() as unit:
                if not unit.state.active:
                    return
                incidents = [
                    (key, copy.deepcopy(value))
                    for key, value in unit.state.incidents.items()
                    if value["run_id"] == unit.state.run_id
                    and value["revision"] != value.get("timeline_revision")
                ]
            for incident_id, incident in incidents:
                device = self.inventory[incident["device_id"]]

                async def write(key: str = incident_id, data: dict[str, Any] = incident) -> None:
                    rows = sorted(data["timeline"], key=lambda row: row["ts"])
                    artifact = await asyncio.to_thread(
                        self.evidence.timeline, key, data["revision"], rows
                    )
                    async with self.repository.transaction() as unit:
                        current = unit.state.incidents[key]
                        current["timeline_artifact"] = artifact
                        current["timeline_revision"] = data["revision"]
                        self._record(
                            unit,
                            "incident",
                            key,
                            {k: v for k, v in current.items() if k != "snapshot"},
                            self.clock_ms(),
                        )

                await self._effect(
                    f"{incident_id}:timeline:{incident['revision']}",
                    "A3",
                    "write_timeline",
                    device,
                    write,
                )
