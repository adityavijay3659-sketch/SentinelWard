"""A5/A7/A8: journalled facts and human commands, asynchronous wording only."""

from __future__ import annotations

import asyncio
import base64
import copy
import time
from collections.abc import Callable
from contextlib import nullcontext, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from sentinelward.adapters.granite import UnavailableWriter, Writer
from sentinelward.alerts import AlertRecord, AlertStore
from sentinelward.contracts import (
    ActionMessage,
    DemoControlMessage,
    RecordMessage,
    RequestMessage,
    VerdictMessage,
)
from sentinelward.demo_lifecycle import SOURCE_END_SECONDS, SOURCE_JOIN_SECONDS
from sentinelward.phase4 import Phase4Coordinator
from sentinelward.phase5_contracts import (
    REPORT_FIELDS,
    BriefingData,
    Composition,
    ConfirmReport,
    CoverageReceipt,
    EditReport,
    Fact,
    FactSnapshot,
    GenerateBriefing,
    HumanCommand,
    HumanGrant,
    MarkSent,
    Narrative,
    NurseLoad,
    Phase5Record,
    ReportData,
    ReportField,
    StaffProfile,
    SuppressionReceipt,
    WorkloadData,
    digest,
)
from sentinelward.phase5_diagnostics import GenerationFailure
from sentinelward.phase5_facts import covered_ms, render_composition, template
from sentinelward.phase5_state import Repository, Unit
from sentinelward.report_pdf import export_pdf


@dataclass
class Phase5Coordinator:
    repository: Repository
    phase4: Phase4Coordinator
    alerts: AlertStore
    staff: StaffProfile
    report_profile: dict[str, str | bool] = field(default_factory=dict)
    writer: Writer = field(default_factory=UnavailableWriter)
    clock_ms: Callable[[], int] = field(default=lambda: time.time_ns() // 1_000_000)
    generation_timeout_s: float = 120
    demo_timeout_s: float = 45
    queue_limit: int = 8
    worker_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    inference_task: asyncio.Task[Composition] | None = field(default=None, init=False)
    inference_run: str | None = field(default=None, init=False)
    inference_record: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if (
            not 0 < self.generation_timeout_s <= 120
            or not 0 < self.demo_timeout_s <= 45
            or not 1 <= self.queue_limit <= 8
        ):
            raise ValueError("generation budget exceeds approved bounds")
        if any(k not in REPORT_FIELDS for k in self.report_profile):
            raise ValueError("unknown report profile field")

    def _active(self, unit: Unit, run_id: str | None = None) -> None:
        if (
            not unit.runtime.active
            or not unit.runtime.run_id
            or (run_id is not None and run_id != unit.runtime.run_id)
        ):
            raise ValueError("inactive or stale Phase 5 run")

    def _audit(self, unit: Unit, name: str, actor: str, body: dict[str, Any]) -> None:
        unit.audits.append(("phase5." + name, actor, body))

    def _record(self, unit: Unit, kind: str, key: str, data: dict[str, Any]) -> None:
        owner = {"report": "A5", "workload": "A7", "briefing": "A8"}[kind]
        models: dict[str, type[Phase5Record]] = {
            "report": ReportData,
            "workload": WorkloadData,
            "briefing": BriefingData,
        }
        model = models[kind]
        validated = model.model_validate(data).model_dump(mode="json")
        unit.put(kind, key, validated)
        wire = RecordMessage.model_validate(
            {
                "v": 1,
                "type": "record",
                "ts": data["as_of"],
                "kind": kind,
                "record_id": key,
                "by": owner,
                "data": validated,
            }
        )
        unit.events[:] = [
            (topic, body)
            for topic, body in unit.events
            if not (
                topic == "ward/record"
                and body.get("record_id") == key
                and body.get("data", {}).get("revision") == data["revision"]
            )
        ]
        unit.events.append(("ward/record", wire.model_dump(mode="json")))
        self._audit(
            unit, kind + ".revision", owner, {"record_id": key, "revision": data["revision"]}
        )

    def _action(
        self,
        unit: Unit,
        owner: str,
        action: str,
        target: str,
        by: str | None = None,
        *,
        undo: str | None = None,
    ) -> str:
        from sentinelward.policy import AGENT_ACTIONS

        if action not in AGENT_ACTIONS[owner]:
            raise ValueError("action outside owner capability")
        action_id = "act_" + digest([unit.runtime.run_id, owner, action, target, by, undo])[:32]
        message = ActionMessage(
            v=1,
            type="action",
            action_id=action_id,
            ts=self.clock_ms(),
            by=owner,
            action=action,
            detail=f"{target}; verified record/audit updated",
            undo_id=action_id
            if undo is None and action != "start_clock" and ":human-attestation" not in target
            else None,
            undoes=undo,
            approved_by=by,
            result="ok",
        )
        unit.events.append(("ward/action", message.model_dump(mode="json")))
        unit.put(
            "action",
            action_id,
            {
                "run_id": unit.runtime.run_id,
                "owner": owner,
                "target": target,
                "action": action,
                "revision": 1,
                "undone": False,
                "message": message.model_dump(mode="json"),
            },
        )
        self._audit(unit, "action", owner, message.model_dump(mode="json"))
        return action_id

    async def handle_control(self, command: DemoControlMessage) -> None:
        # Called under the shared Phase 4 lifecycle gate, after M6/Phase 4 validate.
        async with self.repository.transaction() as unit:
            fingerprint = digest(command.model_dump(mode="json"))
            if unit.runtime.control_hash == fingerprint:
                return
            if command.ts <= unit.runtime.control_ts:
                raise ValueError("stale Phase 5 control")
            if command.cmd == "run" and command.run_id in unit.runtime.used_runs:
                raise ValueError("run identity reused")
            if command.cmd == "reset" and unit.runtime.run_id not in {None, command.run_id}:
                raise ValueError("reset identity mismatch")
            unit.retire_run = unit.runtime.run_id
            if self.inference_task is not None and self.inference_run == unit.runtime.run_id:
                self.inference_task.cancel()
            for key, job in unit.list("job"):
                if job["state"] in {"pending", "running"}:
                    job.update(state="retired", reason="run_reset")
                    unit.put("job", key, job)
            # Clock and report history are retained. New active namespace starts empty.
            unit.runtime.run_id = command.run_id
            unit.runtime.active = command.cmd == "run"
            unit.runtime.start_ts = ((command.ts + 999) // 1000) * 1000
            unit.runtime.end_ts = unit.runtime.start_ts + (1200 - command.start_at_s) * 1000
            unit.runtime.start_at_s = command.start_at_s
            unit.runtime.control_ts, unit.runtime.control_hash = command.ts, fingerprint
            unit.runtime.workload_minute = -1
            unit.runtime.demo_briefing = False
            unit.runtime.shift_boundary = unit.runtime.start_ts
            if command.cmd == "run":
                unit.runtime.used_runs.append(command.run_id)
            self._audit(unit, "control", "backend", command.model_dump(mode="json"))

    async def register_grant(self, grant: HumanGrant) -> None:
        async with self.repository.transaction() as unit:
            self._active(unit, grant.run_id)
            prior = unit.get("grant", grant.request_id)
            data = grant.model_dump(mode="json")
            if prior is not None and prior != data:
                raise ValueError("authorization cannot be replaced")
            if prior is not None:
                return
            if grant.expires_ts <= self.clock_ms():
                raise ValueError("expired authorization")
            unit.put("grant", grant.request_id, data)
            self._audit(
                unit,
                "authorization",
                "backend",
                {"request_id": grant.request_id, "by": grant.principal.by, "action": grant.action},
            )

    def _authorize(
        self, unit: Unit, command: HumanCommand, action: str, target: str
    ) -> dict[str, Any] | None:
        self._active(unit, command.run_id)
        raw = unit.get("grant", command.request_id)
        if raw is None:
            raise PermissionError("trusted human authorization required")
        grant = HumanGrant.model_validate(raw)
        roles = {"it"} if action != "briefing" else {"nurse", "doctor"}
        if (
            grant.action != action
            or grant.target_id != target
            or grant.principal.by != command.by
            or grant.principal.role not in roles
        ):
            raise PermissionError("authorization role/action/target mismatch")
        prior = unit.get("command", command.request_id)
        fingerprint = digest([action, target, command.model_dump(mode="json")])
        if prior is not None:
            if prior["hash"] != fingerprint:
                raise ValueError("request identity reused with different content")
            return dict(copy.deepcopy(prior["result"]))
        if (
            grant.expires_ts < self.clock_ms()
            or command.ts < unit.runtime.start_ts
            or command.ts > self.clock_ms() + 5000
        ):
            raise PermissionError("expired or stale human command")
        return None

    def _receipt(
        self, unit: Unit, command: HumanCommand, action: str, target: str, result: dict[str, Any]
    ) -> None:
        unit.put(
            "command",
            command.request_id,
            {
                "run_id": command.run_id,
                "hash": digest([action, target, command.model_dump(mode="json")]),
                "result": result,
            },
        )
        self._audit(
            unit,
            action,
            command.by,
            {
                "request_id": command.request_id,
                "target": target,
                "revision": result.get("revision"),
            },
        )

    async def observe_alert(self, wire: Any) -> None:
        alert: AlertRecord | None = await self.alerts.get_alert(wire.alert_id)
        if alert is None:
            return
        async with self.repository.transaction() as unit:
            if (
                not unit.runtime.active
                or alert.demo_run_id != unit.runtime.run_id
                or wire.ts < unit.runtime.start_ts
                or wire.ts > self.clock_ms() + 5000
                or wire.ts > alert.updated_ts
            ):
                return
            prior = unit.get("alert", alert.alert_id)
            if prior is None or wire.ts >= prior["ts"]:
                unit.put(
                    "alert",
                    alert.alert_id,
                    {
                        "run_id": unit.runtime.run_id,
                        "ts": wire.ts,
                        "bed_id": alert.bed_id,
                        "active": alert.active,
                        "priority": wire.priority,
                        "verdict": wire.verdict.value,
                        "status": wire.status,
                        "acked_by": wire.acked_by,
                    },
                )
            for staff_id in set(wire.to):
                if alert.roster is not None and staff_id == alert.roster.on_call_doctor:
                    continue
                role = (
                    "nurse"
                    if alert.roster is not None and staff_id in alert.roster.unit_nurses
                    else "unknown"
                )
                key = digest([unit.runtime.run_id, alert.alert_id, staff_id])
                if unit.get("alarm", key) is None:
                    unit.put(
                        "alarm",
                        key,
                        {
                            "run_id": unit.runtime.run_id,
                            "ts": wire.ts,
                            "alert_id": alert.alert_id,
                            "staff_id": staff_id,
                            "role": role,
                            "roster_version": alert.roster.assignment_version
                            if alert.roster
                            else "unavailable",
                            "basis": "screen_routed",
                        },
                    )

    async def observe_lifecycle(self) -> None:
        state = await self.phase4.snapshot()
        now = self.clock_ms()
        async with self.repository.transaction() as unit:
            if not unit.runtime.active or state["run_id"] != unit.runtime.run_id:
                return
            until = min(now, unit.runtime.end_ts)
            for device in self.phase4.inventory.values():
                bed = device.bed_id
                projection = state["bed_projections"].get(bed, {})
                last = state["latest"].get(bed)
                decision = unit.get("decision", bed)
                status = (
                    "offline"
                    if bed in state["offline"]
                    else "untrusted"
                    if bed in state["untrusted"]
                    else "trusted"
                    if last
                    and last["ts"] >= now - 3000
                    and decision
                    and decision["trusted_now"]
                    and decision["ts"] >= now - 5000
                    and projection.get("state") != "reconnecting"
                    else "unknown"
                )
                cursor = unit.get("coverage_cursor", bed)
                segment_id = None
                if cursor:
                    start = cursor["ts"]
                    end = until
                    # A trusted observation grants at most three seconds of known freshness.
                    if cursor["state"] == "trusted":
                        end = min(end, cursor["fresh_until"])
                    if end > start:
                        receipt = CoverageReceipt(
                            receipt_id="cov_"
                            + digest(
                                [unit.runtime.run_id, bed, start, cursor["state"], "native_segment"]
                            )[:32],
                            run_id=str(unit.runtime.run_id),
                            bed_id=bed,
                            start_ts=start,
                            end_ts=end,
                            state=cursor["state"],
                            source="local_lifecycle",
                        )
                        incompatible = [
                            r
                            for _, r in unit.list("coverage")
                            if r["bed_id"] == bed
                            and r["state"] not in {"unknown", receipt.state}
                            and receipt.state != "unknown"
                            and max(r["start_ts"], start) < min(r["end_ts"], end)
                        ]
                        if incompatible:
                            unit.put(
                                "coverage_conflict",
                                receipt.receipt_id,
                                {
                                    "run_id": unit.runtime.run_id,
                                    "bed_id": bed,
                                    "start_ts": start,
                                    "end_ts": end,
                                },
                            )
                        else:
                            previous = unit.get("coverage", cursor.get("segment_id", ""))
                            if (
                                previous is not None
                                and previous["source"] == "local_lifecycle"
                                and previous["state"] == receipt.state
                                and previous["end_ts"] == start
                            ):
                                receipt = receipt.model_copy(
                                    update={
                                        "receipt_id": previous["receipt_id"],
                                        "start_ts": previous["start_ts"],
                                    }
                                )
                            unit.put(
                                "coverage", receipt.receipt_id, receipt.model_dump(mode="json")
                            )
                            if status == cursor["state"] and end == until:
                                segment_id = receipt.receipt_id
                # Do not extend current offline/untrusted state backwards to before it was observed.
                unit.put(
                    "coverage_cursor",
                    bed,
                    {
                        "run_id": unit.runtime.run_id,
                        "ts": until,
                        "state": status,
                        "segment_id": segment_id,
                        "fresh_until": min(last["ts"] + 3000, decision["ts"] + 5000)
                        if last and decision
                        else until,
                        "projection": projection.get("state", "unknown"),
                    },
                )

    async def sync_alerts(self) -> None:
        async with self.repository.transaction() as unit:
            identifiers = [key for key, _ in unit.list("alert")] if unit.runtime.active else []
        for identifier in identifiers:
            actual = await self.alerts.get_alert(identifier)
            if actual is not None:
                await self.observe_alert(actual.wire())

    async def ingest_coverage(self, receipt: CoverageReceipt) -> None:
        async with self.repository.transaction() as unit:
            self._active(unit, receipt.run_id)
            if receipt.start_ts < unit.runtime.start_ts or receipt.end_ts > min(
                self.clock_ms(), unit.runtime.end_ts
            ):
                raise ValueError("coverage receipt is outside causal run interval")
            prior = unit.get("coverage", receipt.receipt_id)
            data = receipt.model_dump(mode="json")
            if prior is not None and prior != data:
                raise ValueError("coverage receipt immutable")
            existing = [
                CoverageReceipt.model_validate(v)
                for _, v in unit.list("coverage")
                if v["bed_id"] == receipt.bed_id
            ]
            if any(
                r.state not in {receipt.state, "unknown"}
                and receipt.state != "unknown"
                and max(r.start_ts, receipt.start_ts) < min(r.end_ts, receipt.end_ts)
                for r in existing
            ):
                raise ValueError("conflicting coverage receipt")
            unit.put("coverage", receipt.receipt_id, data)

    async def ingest_suppression(self, receipt: SuppressionReceipt) -> None:
        async with self.repository.transaction() as unit:
            self._active(unit, receipt.run_id)
            if receipt.ts < unit.runtime.start_ts or receipt.ts > self.clock_ms():
                raise ValueError("suppression receipt outside causal run")
            key = digest([receipt.run_id, receipt.bed_id, receipt.alarm_id])
            prior = unit.get("suppression", key)
            data = receipt.model_dump(mode="json")
            if prior and prior != data:
                raise ValueError("conflicting suppression receipt")
            unit.put("suppression", key, data)

    def _snapshot(
        self,
        unit: Unit,
        kind: str,
        since: int,
        as_of: int,
        rows: list[tuple[str, int | str | None, str, str]],
        versions: dict[str, int],
    ) -> FactSnapshot:
        facts = []
        for index, (subject, value, predicate, status) in enumerate(rows):
            facts.append(
                Fact.model_validate(
                    dict(
                        fact_id=f"f{index}",
                        predicate=predicate,
                        subject=subject,
                        value=value,
                        unit="events"
                        if predicate == "count"
                        else "ms"
                        if predicate == "duration"
                        else "text",
                        status=status,
                        source=(
                            "coverage_ledger"
                            if predicate == "duration"
                            else "suppression_receipts"
                            if subject == "recorded_suppressed_alarms"
                            else "A1_alert_records"
                            if subject == "active_urgent_alerts"
                            else "A6_ticket_records"
                            if subject == "currently_open_tickets"
                            else "phase4_lifecycle"
                            if "beds" in subject
                            else "A3_incident_snapshot"
                        ),
                        revision=1,
                        start_ts=since,
                        end_ts=as_of,
                    )
                )
            )
        data = {
            "run_id": unit.runtime.run_id,
            "kind": kind,
            "since": since,
            "as_of": as_of,
            "facts": [f.model_dump(mode="json") for f in facts],
            "source_versions": versions,
        }
        snapshot = FactSnapshot.model_validate(
            {"snapshot_id": "facts_" + digest(data)[:32], **data}
        )
        unit.put("snapshot", snapshot.snapshot_id, snapshot.model_dump(mode="json"))
        return snapshot

    def _queue(
        self, unit: Unit, kind: str, record_id: str, revision: int, snapshot: FactSnapshot
    ) -> None:
        if isinstance(self.writer, UnavailableWriter):
            record = unit.get(kind, record_id)
            assert record is not None
            record["narrative"] = template(snapshot, "model_disabled").model_dump(mode="json")
            self._record(unit, kind, record_id, record)
            return
        cached = unit.get("cache", digest([snapshot.source_hash, self.writer.identity, "phase5-3"]))
        if cached:
            record = unit.get(kind, record_id)
            assert record is not None
            narrative = Narrative.model_validate(cached["narrative"])
            assert narrative.composition is not None
            render_composition(snapshot, narrative.composition)
            record["narrative"] = narrative.model_dump(mode="json")
            self._record(unit, kind, record_id, record)
            return
        if (
            sum(j["state"] in {"pending", "running"} for _, j in unit.list("job"))
            >= self.queue_limit
        ):
            record = unit.get(kind, record_id)
            assert record is not None
            record["narrative"] = template(snapshot, "queue_full").model_dump(mode="json")
            self._record(unit, kind, record_id, record)
            return
        key = (
            "job_" + digest([record_id, revision, snapshot.source_hash, self.writer.identity])[:32]
        )
        now = self.clock_ms()
        record = unit.get(kind, record_id)
        timeout = (
            self.demo_timeout_s
            if record and record.get("scope") == "demo_run"
            else self.generation_timeout_s
        )
        unit.put(
            "job",
            key,
            {
                "run_id": unit.runtime.run_id,
                "kind": kind,
                "record_id": record_id,
                "revision": revision,
                "snapshot_id": snapshot.snapshot_id,
                "state": "pending",
                "queued_ts": now,
                "deadline_ts": min(now + int(timeout * 1000), unit.runtime.end_ts or now + 120000),
                "attempts": 0,
            },
        )

    async def confirm_report(self, incident_id: str, command: ConfirmReport) -> dict[str, Any]:
        async with self.phase4.lifecycle_gate:
            state = await self.phase4.snapshot()
            incident = state["incidents"].get(incident_id)
            if incident is None or incident["run_id"] != command.run_id:
                raise LookupError("current incident not found")
            async with self.repository.transaction() as unit:
                replay = self._authorize(unit, command, "confirm_report", incident_id)
                if replay is not None:
                    return replay
                key = "rp_" + digest([command.run_id, incident_id])[:32]
                prior = unit.get("report", key)
                if prior:
                    existing = {"record_id": key, **copy.deepcopy(prior)}
                    self._receipt(unit, command, "confirm_report", incident_id, existing)
                    return existing
                noticed = command.noticed_ts if command.noticed_ts is not None else incident["ts"]
                if noticed > command.ts or noticed < unit.runtime.start_ts:
                    raise ValueError("notice timestamp outside known run")
                if command.noticed_ts is not None and not command.notice_reason:
                    raise ValueError("reviewed notice anchor requires provenance")
                fields = {
                    name: ReportField(
                        value=self.report_profile.get(name),
                        status="profile" if name in self.report_profile else "missing",
                        source="configured_demo_profile"
                        if name in self.report_profile
                        else "unavailable",
                    )
                    for name in REPORT_FIELDS
                }
                device = self.phase4.inventory[incident["device_id"]]
                observed_verdicts = sorted(
                    {
                        row.get("verdict", row.get("body", {}).get("verdict", ""))
                        for row in incident["timeline"]
                        if row.get("kind") == "verdict"
                    }
                )
                if observed_verdicts:
                    fields["symptoms"] = ReportField(
                        value="Recorded classification(s): "
                        + ", ".join(observed_verdicts)
                        + "; human interpretation required",
                        status="observed",
                        source="A3_observed_verdict_timeline",
                    )
                scoped_effects = [
                    e
                    for e in state["effects"].values()
                    if e.get("run_id") == command.run_id and e.get("bed_id") == incident["bed_id"]
                ]
                if scoped_effects:
                    fields["actions_taken"] = ReportField(
                        value="; ".join(
                            sorted(
                                {
                                    f"{e['agent']} {e['action']}: {e['status']}"
                                    for e in scoped_effects
                                }
                            )
                        ),
                        status="observed",
                        source="durable_action_outcomes",
                    )
                fields["model"] = ReportField(
                    value=device.model, status="observed", source="inventory"
                )
                fields["evidence_summary"] = ReportField(
                    value=(
                        "Available evidence is listed separately; missing context remains explicit"
                    ),
                    status="observed",
                    source="A3",
                )
                successful = sum(
                    e["status"] == "ok"
                    for e in state["effects"].values()
                    if e.get("run_id") == command.run_id and e.get("bed_id") == incident["bed_id"]
                )
                snapshot = self._snapshot(
                    unit,
                    "report",
                    unit.runtime.start_ts,
                    command.ts,
                    [
                        ("incidents", 1, "count", "observed"),
                        (
                            "available_evidence_files",
                            sum(bool(e.get("available")) for e in incident["evidence"]),
                            "count",
                            "observed",
                        ),
                        ("successful_actions", successful, "count", "observed"),
                        (
                            "missing_report_fields",
                            sum(f.value is None for f in fields.values()),
                            "count",
                            "derived",
                        ),
                        (
                            "report_state",
                            "Human review and external sending required",
                            "state",
                            "observed",
                        ),
                    ],
                    {incident_id: incident["revision"]},
                )
                report = ReportData(
                    run_id=command.run_id,
                    revision=1,
                    as_of=command.ts,
                    incident_id=incident_id,
                    status="needs_review",
                    occurred_ts=None,
                    observed_ts=incident["ts"],
                    noticed_ts=noticed,
                    confirmed_ts=command.ts,
                    provisional_notice=command.noticed_ts is None,
                    notice_provenance=command.notice_reason
                    or "first machine observation; provisional",
                    deadline_ts=noticed + 6 * 3600_000,
                    fields=fields,
                    missing_fields=[k for k, v in fields.items() if v.value is None],
                    evidence=incident["evidence"],
                    narrative=template(snapshot),
                    snapshot_id=snapshot.snapshot_id,
                    checklist={
                        "facts_checked": False,
                        "evidence_reviewed": False,
                        "approved": False,
                    },
                )
                data = report.model_dump(mode="json")
                self._record(unit, "report", key, data)
                self._action(unit, "A5", "draft_report", key, command.by)
                self._action(unit, "A5", "start_clock", key, command.by)
                self._queue(unit, "report", key, 1, snapshot)
                data = {"record_id": key, **copy.deepcopy(unit.get("report", key) or data)}
                self._receipt(unit, command, "confirm_report", incident_id, data)
                return data

    async def edit_report(self, report_id: str, command: EditReport) -> dict[str, Any]:
        async with self.phase4.lifecycle_gate, self.repository.transaction() as unit:
            replay = self._authorize(unit, command, "edit_report", report_id)
            if replay is not None:
                return replay
            raw = unit.get("report", report_id)
            if raw is None:
                raise LookupError("report not found")
            report = ReportData.model_validate(raw)
            if report.revision != command.expected_revision or report.status in {
                "human_marked_sent",
                "superseded",
            }:
                raise ValueError("stale or immutable report revision")
            if any(name not in REPORT_FIELDS for name in command.fields):
                raise ValueError("unsupported report field")
            material = (
                bool(command.fields)
                or command.description is not None
                or command.noticed_ts is not None
            )
            if command.noticed_ts is not None:
                if (
                    not command.notice_reason
                    or not unit.runtime.start_ts <= command.noticed_ts <= command.ts
                ):
                    raise ValueError(
                        "reviewed notice correction requires valid timestamp and provenance"
                    )
                self._audit(
                    unit,
                    "notice.corrected",
                    command.by,
                    {
                        "before": report.noticed_ts,
                        "after": command.noticed_ts,
                        "reason": command.notice_reason,
                    },
                )
                report.noticed_ts = command.noticed_ts
                report.deadline_ts = command.noticed_ts + 6 * 3600_000
                report.provisional_notice = False
                report.notice_provenance = command.notice_reason
            for name, value in command.fields.items():
                report.fields[name] = ReportField(
                    value=value,
                    status="attested" if value is not None else "missing",
                    source="human:" + command.by,
                )
            if command.description is not None:
                report.narrative = Narrative(
                    text=command.description,
                    generator="human",
                    verified=False,
                    snapshot_hash=report.narrative.snapshot_hash,
                )
            report.missing_fields = [
                name for name, value in report.fields.items() if value.value is None
            ]
            if material and report.narrative.generator != "human":
                original_snapshot = unit.get("snapshot", report.snapshot_id)
                assert original_snapshot is not None
                previous_snapshot = FactSnapshot.model_validate(original_snapshot)
                updated_facts = [
                    fact.model_copy(
                        update={
                            "value": len(report.missing_fields),
                            "end_ts": self.clock_ms(),
                            "source": "human_report_revision",
                        }
                    )
                    if fact.subject == "missing_report_fields"
                    else fact
                    for fact in previous_snapshot.facts
                ]
                updated_snapshot = previous_snapshot.model_copy(
                    update={
                        "snapshot_id": "facts_"
                        + digest([report_id, report.revision + 1, command.model_dump(mode="json")])[
                            :32
                        ],
                        "as_of": self.clock_ms(),
                        "facts": updated_facts,
                    }
                )
                unit.put(
                    "snapshot",
                    updated_snapshot.snapshot_id,
                    updated_snapshot.model_dump(mode="json"),
                )
                report.snapshot_id = updated_snapshot.snapshot_id
                report.narrative = template(updated_snapshot, "human_fields_updated")
            report.human_edited = True
            report.revision += 1
            report.as_of = self.clock_ms()
            report.pdf = None
            # Material edits require a separate review of the new revision.
            report.checklist = {
                "facts_checked": command.facts_checked and not material,
                "evidence_reviewed": command.evidence_reviewed and not material,
                "approved": command.approved and not material,
            }
            report.checked_revision = report.revision if all(report.checklist.values()) else None
            report.status = (
                "ready_for_human_send"
                if report.checked_revision
                and not report.provisional_notice
                and not report.missing_fields
                else "needs_review"
            )
            data = report.model_dump(mode="json")
            self._record(unit, "report", report_id, data)
            for key, job in unit.list("job"):
                if job["record_id"] == report_id and job["state"] in {"pending", "running"}:
                    job.update(state="retired", reason="human_revision")
                    unit.put("job", key, job)
            if self.inference_task is not None and self.inference_record == report_id:
                self.inference_task.cancel()
            self._action(
                unit, "A5", "draft_report", report_id + ":" + str(report.revision), command.by
            )
            self._receipt(unit, command, "edit_report", report_id, data)
            return data

    async def pdf(self, report_id: str) -> tuple[bytes, dict[str, Any]]:
        async with self.phase4.lifecycle_gate, self.repository.transaction() as unit:
            self._active(unit)
            raw = unit.get("report", report_id)
            if raw is None:
                raise LookupError("report not found")
            report = ReportData.model_validate(raw)
            key = report_id + ":" + str(report.revision)
            cached = unit.get("pdf", key)
            if cached:
                return base64.b64decode(cached["body"]), cached["metadata"]
            body, metadata = await asyncio.to_thread(export_pdf, report_id, report)
            unit.put(
                "pdf",
                key,
                {
                    "run_id": unit.runtime.run_id,
                    "body": base64.b64encode(body).decode(),
                    "metadata": metadata,
                },
            )
            raw["pdf"] = metadata
            unit.put("report", report_id, raw)
            self._audit(unit, "pdf", "A5", {"report_id": report_id, **metadata})
            return body, metadata

    async def mark_sent(self, report_id: str, command: MarkSent) -> dict[str, Any]:
        async with self.phase4.lifecycle_gate, self.repository.transaction() as unit:
            replay = self._authorize(unit, command, "mark_report_sent", report_id)
            if replay is not None:
                return replay
            raw = unit.get("report", report_id)
            if raw is None:
                raise LookupError("report not found")
            report = ReportData.model_validate(raw)
            if report.revision != command.expected_revision or report.status in {
                "human_marked_sent",
                "superseded",
            }:
                raise ValueError("stale or sent revision")
            if (
                report.checked_revision != report.revision
                or not all(report.checklist.values())
                or report.provisional_notice
            ):
                raise ValueError("reviewed notice/checklist required")
            if (
                report.pdf is None
                or report.pdf["sha256"] != command.document_hash
                or report.pdf["revision"] != report.revision
            ):
                raise ValueError("exact exported document hash required")
            if report.missing_fields and (
                not command.partial
                or set(command.acknowledged_missing) != set(report.missing_fields)
                or not command.note
            ):
                raise ValueError(
                    "partial-submission attestation must acknowledge all missing fields"
                )
            if command.sent_ts < report.noticed_ts or command.sent_ts > self.clock_ms() + 5000:
                raise ValueError("invalid human send timestamp")
            report.sent = {
                "by": command.by,
                "sent_ts": command.sent_ts,
                "attested_ts": command.ts,
                "submitted_revision": report.revision,
                "document_hash": command.document_hash,
                "partial": command.partial,
                "follow_up": report.missing_fields,
                "note": command.note,
                "receipt_verified": False,
            }
            report.status = "human_marked_sent"
            report.revision += 1
            report.as_of = self.clock_ms()
            data = report.model_dump(mode="json")
            self._record(unit, "report", report_id, data)
            # Locked action.by accepts agents only. Human attestation lives in audit/data;
            # this A5 record update retains approved_by and does not claim sending.
            self._action(unit, "A5", "draft_report", report_id + ":human-attestation", command.by)
            self._receipt(unit, command, "mark_report_sent", report_id, data)
            return data

    def _workload(self, unit: Unit, now: int) -> None:
        since = max(0, now - 2 * 3600_000)
        roster_valid = self.staff.valid_until >= now
        rows = [row for _, row in unit.list("alarm") if since < row["ts"] <= now]
        known = sorted(
            set(self.staff.nurses) | {r["staff_id"] for r in rows if r["role"] == "nurse"}
        )
        loads = [
            NurseLoad(
                staff_id=staff,
                count=sum(r["staff_id"] == staff and r["role"] == "nurse" for r in rows),
                overloaded=sum(r["staff_id"] == staff and r["role"] == "nurse" for r in rows) > 40,
                coverage="complete"
                if roster_valid and unit.runtime.start_ts <= since
                else "partial",
            )
            for staff in known
        ]
        overload = [r.staff_id for r in loads if r.overloaded]
        previous = unit.get("workload", "wl_" + str(unit.runtime.run_id))
        previous_overload = (
            [r["staff_id"] for r in previous["nurses"] if r["overloaded"]] if previous else []
        )
        charge = self.staff.charge_nurse if roster_valid else None
        notification = (
            "not_required" if not overload else "screen_routed" if charge else "unresolved_roster"
        )
        data = WorkloadData.model_validate(
            dict(
                run_id=unit.runtime.run_id,
                revision=(previous["revision"] + 1) if previous else 1,
                as_of=now,
                since=since,
                nurses=loads,
                unassigned_events=sum(r["role"] == "unknown" for r in rows),
                charge_nurse=charge,
                notification=notification,
                roster_version=self.staff.version if roster_valid else None,
            )
        ).model_dump(mode="json")
        key = "wl_" + str(unit.runtime.run_id)
        self._record(unit, "workload", key, data)
        for staff in sorted(set(overload) - set(previous_overload)):
            if charge:
                self._action(unit, "A7", "warn_workload", staff + ":" + str(now // 60000))
                self._audit(
                    unit,
                    "workload.warning",
                    "A7",
                    {"staff_id": staff, "charge_nurse": charge, "state": "screen_routed"},
                )

    def _briefing(
        self,
        unit: Unit,
        state: dict[str, Any],
        key: str,
        since: int,
        as_of: int,
        scope: str,
        by: str | None = None,
    ) -> dict[str, Any]:
        if (
            since < unit.runtime.start_ts
            or since > as_of
            or as_of > min(self.clock_ms(), unit.runtime.end_ts)
        ):
            raise ValueError("briefing interval outside causal available run")
        incidents = [
            (k, v)
            for k, v in state["incidents"].items()
            if v["run_id"] == unit.runtime.run_id and since <= v["ts"] < as_of
        ]
        tickets = [
            v
            for v in state["tickets"].values()
            if v["run_id"] == unit.runtime.run_id and v["status"] != "done"
        ]
        rows: list[tuple[str, int | str | None, str, str]] = [
            ("incidents", len(incidents), "count", "observed"),
            ("currently_open_tickets", len(tickets), "count", "observed"),
            ("currently_untrusted_beds", len(state["untrusted"]), "count", "observed"),
            ("currently_offline_beds", len(state["offline"]), "count", "observed"),
        ]
        receipts = [CoverageReceipt.model_validate(v) for _, v in unit.list("coverage")]
        for device in self.phase4.inventory.values():
            bed_rows = [r for r in receipts if r.bed_id == device.bed_id]
            first = max(
                since,
                unit.runtime.start_ts
                + max(0, SOURCE_JOIN_SECONDS.get(device.bed_id, 0) - unit.runtime.start_at_s)
                * 1000,
            )
            end = min(
                as_of,
                unit.runtime.start_ts
                + max(0, SOURCE_END_SECONDS.get(device.bed_id, 1200) - unit.runtime.start_at_s)
                * 1000,
                state["offline"].get(device.bed_id, as_of),
            )
            end = max(first, end)
            recording_ms = max(0, end - first)
            conflicts = [
                (r["start_ts"], r["end_ts"])
                for _, r in unit.list("coverage_conflict")
                if r["bed_id"] == device.bed_id
            ]
            covered = covered_ms(
                ((r.start_ts, r.end_ts) for r in bed_rows if r.state != "unknown"),
                conflicts,
                first,
                end,
            )
            blind = covered_ms(
                ((r.start_ts, r.end_ts) for r in bed_rows if r.state == "untrusted"),
                conflicts,
                first,
                end,
            )
            rows.append(
                (
                    device.bed_id + "_blind_time",
                    blind if covered else None,
                    "duration",
                    "derived"
                    if covered == recording_ms
                    else "partial"
                    if covered
                    else "unavailable",
                )
            )
            rows.append(
                (
                    device.bed_id + "_unknown_coverage",
                    max(0, recording_ms - covered),
                    "duration",
                    "derived",
                )
            )
            rows.append(
                (
                    device.bed_id + "_outside_recording_interval",
                    max(0, as_of - since - recording_ms),
                    "duration",
                    "derived",
                )
            )
        suppressions = [r for _, r in unit.list("suppression") if since <= r["ts"] < as_of]
        rows.append(
            (
                "recorded_suppressed_alarms",
                len(suppressions) if suppressions else None,
                "count",
                "partial" if suppressions else "unavailable",
            )
        )
        urgent = [
            copy.deepcopy(r)
            for _, r in unit.list("alert")
            if r["active"] and r["priority"] == "high"
        ]
        rows.append(("active_urgent_alerts", len(urgent), "count", "observed"))
        versions = {k: v["revision"] for k, v in incidents}
        versions.update(
            {
                k: v.get("revision", 1)
                for k, v in state["tickets"].items()
                if v["run_id"] == unit.runtime.run_id
            }
        )
        versions.update(
            {
                k: r.get("end_ts", r.get("ts", 1))
                for kind in ("coverage", "suppression", "alert")
                for k, r in unit.list(kind)
            }
        )
        snapshot = self._snapshot(unit, "briefing", since, as_of, rows, versions)
        prior = unit.get("briefing", key)
        data = BriefingData.model_validate(
            dict(
                run_id=unit.runtime.run_id,
                revision=prior["revision"] + 1 if prior else 1,
                as_of=as_of,
                since=since,
                scope=scope,
                snapshot_id=snapshot.snapshot_id,
                facts=snapshot.facts,
                narrative=template(snapshot),
                urgent=urgent,
            )
        ).model_dump(mode="json")
        self._record(unit, "briefing", key, data)
        self._action(unit, "A8", "write_briefing", key, by)
        self._queue(unit, "briefing", key, data["revision"], snapshot)
        return {"record_id": key, **copy.deepcopy(unit.get("briefing", key) or data)}

    async def generate_briefing(self, command: GenerateBriefing) -> dict[str, Any]:
        async with self.phase4.lifecycle_gate:
            await self.sync_alerts()
            state = await self.phase4.snapshot()
            async with self.repository.transaction() as unit:
                replay = self._authorize(unit, command, "briefing", "WARD")
                if replay is not None:
                    return replay
                key = "br_" + digest([command.run_id, command.request_id])[:32]
                data = self._briefing(
                    unit,
                    state,
                    key,
                    command.since if command.since is not None else unit.runtime.start_ts,
                    command.ts,
                    "on_demand",
                    command.by,
                )
                self._receipt(unit, command, "briefing", "WARD", data)
                return data

    def _last_shift_boundary(self, now: int) -> int | None:
        schedule = self.staff.schedule
        if not schedule.starts:
            return None
        zone = ZoneInfo(schedule.timezone)
        local = datetime.fromtimestamp(now / 1000, UTC).astimezone(zone)
        candidates = []
        for offset in (0, 1):
            day = local.date() - timedelta(days=offset)
            for start in schedule.starts:
                hour, minute = map(int, start.split(":"))
                boundary = datetime.combine(day, datetime.min.time(), zone).replace(
                    hour=hour, minute=minute, fold=0
                )
                # Skip nonexistent local times at a daylight-saving transition.
                epoch = int(boundary.timestamp() * 1000)
                if datetime.fromtimestamp(epoch / 1000, UTC).astimezone(zone).replace(
                    tzinfo=None
                ) != boundary.replace(tzinfo=None):
                    continue
                if epoch <= now:
                    candidates.append(epoch)
        return max(candidates) if candidates else None

    async def advance(self) -> None:
        async with self.phase4.lifecycle_gate:
            await self.sync_alerts()
            await self.observe_lifecycle()
            state = await self.phase4.snapshot()
            now = self.clock_ms()
            async with self.repository.transaction() as unit:
                if not unit.runtime.active:
                    return
                if state["run_id"] != unit.runtime.run_id:
                    return
                if now >= unit.runtime.end_ts:
                    unit.runtime.active = False
                    unit.retire_run = unit.runtime.run_id
                    for key, job in unit.list("job"):
                        if job["state"] in {"pending", "running"}:
                            job.update(state="retired", reason="run_complete")
                            unit.put("job", key, job)
                    return
                minute = now // 60000
                if unit.runtime.workload_minute != minute:
                    self._workload(unit, now)
                    unit.runtime.workload_minute = minute
                onset = unit.runtime.start_ts + max(0, 1140 - unit.runtime.start_at_s) * 1000
                if now >= onset and not unit.runtime.demo_briefing:
                    self._briefing(
                        unit,
                        state,
                        "br_demo_" + str(unit.runtime.run_id),
                        unit.runtime.start_ts,
                        now,
                        "demo_run",
                    )
                    unit.runtime.demo_briefing = True
                boundary = self._last_shift_boundary(now)
                if boundary and boundary > unit.runtime.shift_boundary:
                    self._briefing(
                        unit,
                        state,
                        "br_shift_" + digest([unit.runtime.run_id, boundary])[:32],
                        unit.runtime.shift_boundary,
                        boundary,
                        "configured_shift",
                    )
                    unit.runtime.shift_boundary = boundary

    async def process_one_job(self) -> bool:
        async with self.worker_lock:
            now = self.clock_ms()
            async with self.repository.transaction() as unit:
                if not unit.runtime.active:
                    return False
                eligible = [
                    (k, j)
                    for k, j in unit.list("job")
                    if j["state"] == "pending"
                    or (j["state"] == "running" and j.get("lease_until", 0) <= now)
                ]
                if not eligible:
                    return False
                key, job = min(eligible, key=lambda item: (item[1]["queued_ts"], item[0]))
                snapshot_raw = unit.get("snapshot", job["snapshot_id"])
                assert snapshot_raw is not None
                snapshot = FactSnapshot.model_validate(snapshot_raw)
                job.update(
                    state="running",
                    lease_until=job["deadline_ts"],
                    attempts=job["attempts"] + 1,
                    started_ts=now,
                    queue_wait_ms=max(0, now - job["queued_ts"]),
                )
                unit.put("job", key, job)
            started = time.monotonic()
            reason: str | None = None
            composition = None
            called_writer = False
            try:
                remaining = (job["deadline_ts"] - self.clock_ms()) / 1000
                if remaining <= 0:
                    raise TimeoutError("job deadline expired")
                self.inference_run, self.inference_record = job["run_id"], job["record_id"]
                self.inference_task = asyncio.create_task(self.writer.compose(snapshot))
                called_writer = True
                composition = await asyncio.wait_for(self.inference_task, timeout=remaining)
                text = render_composition(snapshot, composition)
                result = Narrative(
                    text=text,
                    generator="granite",
                    snapshot_hash=snapshot.source_hash,
                    model_identity=self.writer.identity,
                    composition=composition,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
            except asyncio.CancelledError:
                caller = asyncio.current_task()
                if caller is not None and caller.cancelling():
                    raise
                reason = "generation_cancelled"
                result = template(snapshot, reason)
                result.elapsed_ms = int((time.monotonic() - started) * 1000)
                result.model_identity = self.writer.identity
            except (
                ValueError,
                KeyError,
                TypeError,
                IndexError,
                TimeoutError,
                ConnectionError,
                httpx.HTTPError,
            ) as exc:
                reason = type(exc).__name__
                if isinstance(exc, GenerationFailure):
                    reason = exc.code
                    job["error_stage"] = exc.stage
                result = template(snapshot, reason)
                result.elapsed_ms = int((time.monotonic() - started) * 1000)
                result.model_identity = self.writer.identity
            finally:
                self.inference_task = None
                self.inference_run = self.inference_record = None
            # No lifecycle lock was held during inference. Revalidate target only;
            # later ordinary source events do not invalidate an as-of document.
            async with self.phase4.lifecycle_gate, self.repository.transaction() as unit:
                current = unit.get("job", key)
                record = unit.get(job["kind"], job["record_id"])
                if (
                    current is None
                    or not unit.runtime.active
                    or unit.runtime.run_id != job["run_id"]
                    or current["state"] == "retired"
                    or record is None
                    or record["revision"] != job["revision"]
                    or record.get("human_edited")
                    or record["status"] in {"human_marked_sent", "superseded"}
                    or self.clock_ms() >= unit.runtime.end_ts
                ):
                    if current is not None:
                        current.update(state="retired", reason="stale_run_or_human_revision")
                        unit.put("job", key, current)
                    return True
                current.update(
                    state="accepted" if reason is None else "fallback",
                    reason=reason,
                    elapsed_ms=result.elapsed_ms,
                    model_identity=self.writer.identity,
                    diagnostics=copy.deepcopy(getattr(self.writer, "last_metrics", {}))
                    if called_writer
                    else {},
                    error_stage=job.get("error_stage"),
                    completed_ts=self.clock_ms(),
                )
                if reason is None and self.clock_ms() > job["deadline_ts"]:
                    reason = "job_deadline_exceeded"
                    elapsed_ms = result.elapsed_ms
                    result = template(snapshot, reason)
                    result.elapsed_ms = elapsed_ms
                    result.model_identity = self.writer.identity
                    current.update(state="fallback", reason=reason)
                unit.put("job", key, current)
                if reason is None:
                    unit.put(
                        "cache",
                        digest([snapshot.source_hash, self.writer.identity, "phase5-3"]),
                        {
                            "run_id": unit.runtime.run_id,
                            "narrative": result.model_dump(mode="json"),
                        },
                    )
                if reason is None:
                    record["narrative"] = result.model_dump(mode="json")
                    record["revision"] += 1
                    if job["kind"] == "report":
                        record.update(
                            pdf=None,
                            checked_revision=None,
                            checklist={
                                "facts_checked": False,
                                "evidence_reviewed": False,
                                "approved": False,
                            },
                        )
                    self._record(unit, job["kind"], job["record_id"], record)
                self._audit(
                    unit,
                    "generation",
                    "A5" if job["kind"] == "report" else "A8",
                    {
                        "job_id": key,
                        "state": current["state"],
                        "reason": reason,
                        "snapshot_hash": snapshot.source_hash,
                    },
                )
            return True

    async def undo(
        self, action_id: str, command: HumanCommand, *, gate_held: bool = False
    ) -> dict[str, Any]:
        async with (
            nullcontext() if gate_held else self.phase4.lifecycle_gate,
            self.repository.transaction() as unit,
        ):
            replay = self._authorize(unit, command, "undo", action_id)
            if replay is not None:
                return replay
            original = unit.get("action", action_id)
            if original is None:
                raise LookupError("Phase 5 action not found")
            existing = unit.get("undo", action_id)
            if existing:
                self._receipt(unit, command, "undo", action_id, existing)
                return copy.deepcopy(existing)
            if original["action"] == "start_clock":
                raise ValueError("elapsed reporting clock cannot be undone")
            owner = original["owner"]
            if owner in {"A5", "A8"}:
                kind = "report" if owner == "A5" else "briefing"
                key = original["target"].split(":")[0]
                raw = unit.get(kind, key)
                if (
                    raw is None
                    or raw["revision"] != command.expected_revision
                    or raw.get("sent")
                    or raw.get("human_edited")
                ):
                    raise ValueError("human/sent/stale artifact cannot be superseded")
                raw["status"] = "superseded"
                raw["revision"] += 1
                raw["as_of"] = self.clock_ms()
                self._record(unit, kind, key, raw)
                for job_id, job in unit.list("job"):
                    if job["record_id"] == key and job["state"] in {"pending", "running"}:
                        job.update(state="retired", reason="artifact_superseded")
                        unit.put("job", job_id, job)
                if self.inference_task is not None and self.inference_record == key:
                    self.inference_task.cancel()
            original["undone"] = True
            unit.put("action", action_id, original)
            receipt = {
                "run_id": command.run_id,
                "original_action_id": action_id,
                "undo_action_id": self._action(
                    unit,
                    owner,
                    original["action"],
                    original["target"] + ":superseded",
                    command.by,
                    undo=action_id,
                ),
                "approved_by": command.by,
            }
            unit.put("undo", action_id, receipt)
            self._receipt(unit, command, "undo", action_id, receipt)
            return receipt

    async def handle_request(self, message: RequestMessage, *, gate_held: bool = False) -> bool:
        if message.action != "undo_action":
            return False
        async with self.repository.transaction() as unit:
            original = unit.get("action", message.target_id)
            owned = original is not None
            run = unit.runtime.run_id
            record = unit.get(
                "report" if original and original["owner"] == "A5" else "briefing",
                original["target"].split(":")[0] if original else "",
            )
            revision = record["revision"] if record else 0
        if not owned:
            return False
        if run is None:
            raise ValueError("no active run")
        await self.undo(
            message.target_id,
            HumanCommand(
                request_id=message.request_id,
                by=message.by,
                run_id=run,
                ts=message.ts,
                expected_revision=revision,
            ),
            gate_held=gate_held,
        )
        return True

    async def observe_verdict(self, message: VerdictMessage) -> None:
        async with self.repository.transaction() as unit:
            self._active(unit)
            if message.window_start < unit.runtime.start_ts or message.ts > self.clock_ms() + 5000:
                raise ValueError("verdict outside causal run")
            previous = unit.get("decision", message.bed_id)
            if previous is None or previous["ts"] < message.ts:
                unit.put(
                    "decision",
                    message.bed_id,
                    {
                        "run_id": unit.runtime.run_id,
                        "ts": message.ts,
                        "trusted_now": message.last_trusted_ts is None,
                        "source": "locked_verdict_last_trusted_ts",
                    },
                )

    async def status(self) -> dict[str, Any]:
        await self.sync_alerts()
        async with self.repository.transaction() as unit:
            runtime = unit.runtime.model_dump(mode="json")
            result = {
                "runtime": runtime,
                "records": {
                    kind: [
                        {"record_id": key, **copy.deepcopy(value)} for key, value in unit.list(kind)
                    ]
                    for kind in ("report", "workload", "briefing")
                },
                "jobs": [
                    {"job_id": key, **copy.deepcopy(value)} for key, value in unit.list("job")
                ],
                "urgent": [
                    copy.deepcopy(value)
                    for _, value in unit.list("alert")
                    if unit.runtime.active and value["active"] and value["priority"] == "high"
                ],
            }
            return result

    async def run_worker(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            if not await self.process_one_job():
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=0.25)
