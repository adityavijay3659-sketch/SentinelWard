"""Phase 5 internal data; locked MQTT envelopes remain unchanged."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import ConfigDict, Field, model_validator

from sentinelward.contracts import BedId, Identifier, StaffId, StrictMessage, TimestampMs


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class Fact(StrictMessage):
    fact_id: Identifier
    predicate: Literal["count", "duration", "state", "scope", "missing", "action"]
    subject: Identifier
    value: int | str | None
    unit: Literal["events", "ms", "text"]
    status: Literal["observed", "derived", "attested", "unavailable", "partial"]
    source: Identifier
    revision: int = Field(ge=0)
    start_ts: TimestampMs
    end_ts: TimestampMs

    @model_validator(mode="after")
    def consistency(self) -> Fact:
        if self.end_ts < self.start_ts:
            raise ValueError("invalid fact interval")
        if self.status == "unavailable" and self.value is not None:
            raise ValueError("unavailable fact cannot have a value")
        if self.unit != "text" and self.value is not None and type(self.value) is not int:
            raise ValueError("quantity must be an integer")
        return self


class FactSnapshot(StrictMessage):
    v: Literal[1] = 1
    snapshot_id: Identifier
    run_id: Identifier
    kind: Literal["report", "briefing"]
    since: TimestampMs
    as_of: TimestampMs
    facts: list[Fact] = Field(min_length=1, max_length=64)
    source_versions: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_facts(self) -> FactSnapshot:
        if self.as_of < self.since or len({f.fact_id for f in self.facts}) != len(self.facts):
            raise ValueError("invalid snapshot interval or repeated facts")
        return self

    @property
    def source_hash(self) -> str:
        return digest(self.model_dump(mode="json"))


class Sentence(StrictMessage):
    phrase_id: Literal["count", "duration", "state", "scope", "missing", "action"]
    fact_id: Identifier
    wording: Literal["plain", "concise"] = "plain"


class Composition(StrictMessage):
    v: Literal[1] = 1
    sentences: list[Sentence] = Field(min_length=1, max_length=64)


class CompactComposition(StrictMessage):
    """Model-only wire v2; each bit chooses approved wording for one source fact."""

    v: Literal[2]
    order: Literal["source", "reverse"]
    wording: str = Field(min_length=1, max_length=64, pattern="^[01]+$")

    def expand(self, snapshot: FactSnapshot) -> Composition:
        from sentinelward.phase5_diagnostics import GenerationFailure

        if len(self.wording) != len(snapshot.facts):
            raise GenerationFailure("wording_count_mismatch", "fact_binding")
        sentences = [
            Sentence(
                fact_id=fact.fact_id,
                phrase_id="missing" if fact.status == "unavailable" else fact.predicate,
                wording="concise" if choice == "1" else "plain",
            )
            for fact, choice in zip(snapshot.facts, self.wording, strict=True)
        ]
        return Composition(sentences=sentences if self.order == "source" else sentences[::-1])


class Narrative(StrictMessage):
    model_config = ConfigDict(extra="forbid", frozen=False)
    text: str = Field(max_length=12_000)
    generator: Literal["template", "granite", "human"]
    snapshot_hash: str
    model_identity: str = "none"
    prompt_version: Literal["phase5-1", "phase5-2", "phase5-3"] = "phase5-3"
    phrase_version: Literal["phase5-1"] = "phase5-1"
    verified: bool = True
    fallback_reason: str | None = None
    elapsed_ms: int = Field(default=0, ge=0)
    composition: Composition | None = None


class ReportField(StrictMessage):
    value: str | int | bool | None = None
    status: Literal["observed", "profile", "attested", "missing"] = "missing"
    source: str = "unavailable"

    @model_validator(mode="after")
    def bounded(self) -> ReportField:
        if isinstance(self.value, str) and len(self.value) > 2000:
            raise ValueError("report field exceeds document budget")
        return self


class Principal(StrictMessage):
    by: StaffId
    role: Literal["it", "nurse", "doctor", "operator"]


class HumanGrant(StrictMessage):
    request_id: Identifier
    principal: Principal
    run_id: Identifier
    action: Literal["confirm_report", "edit_report", "mark_report_sent", "briefing", "undo"]
    target_id: Identifier
    expires_ts: TimestampMs


class HumanCommand(StrictMessage):
    v: Literal[1] = 1
    request_id: Identifier
    by: StaffId
    run_id: Identifier
    ts: TimestampMs
    expected_revision: int = Field(default=0, ge=0, strict=True)


class ConfirmReport(HumanCommand):
    noticed_ts: TimestampMs | None = None
    notice_reason: str = Field(default="", max_length=240)


class EditReport(HumanCommand):
    fields: dict[str, str | int | bool | None] = Field(default_factory=dict, max_length=32)
    description: str | None = Field(default=None, max_length=4000)
    facts_checked: bool = False
    evidence_reviewed: bool = False
    approved: bool = False
    noticed_ts: TimestampMs | None = None
    notice_reason: str = Field(default="", max_length=240)


class MarkSent(HumanCommand):
    document_hash: str = Field(min_length=64, max_length=64, pattern="^[a-f0-9]+$")
    sent_ts: TimestampMs
    partial: bool = False
    acknowledged_missing: list[str] = Field(default_factory=list, max_length=32)
    note: str = Field(default="", max_length=240)


class GenerateBriefing(HumanCommand):
    since: TimestampMs | None = None


class ShiftSchedule(StrictMessage):
    timezone: str = "Asia/Kolkata"
    starts: list[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def valid(self) -> ShiftSchedule:
        ZoneInfo(self.timezone)
        if len(set(self.starts)) != len(self.starts):
            raise ValueError("duplicate shift boundary")
        for start in self.starts:
            datetime.strptime(start, "%H:%M")
            if len(start) != 5:
                raise ValueError("shift boundary requires HH:MM")
        return self


class StaffProfile(StrictMessage):
    version: Identifier
    nurses: list[StaffId] = Field(min_length=1, max_length=100)
    charge_nurse: StaffId | None = None
    valid_until: TimestampMs
    schedule: ShiftSchedule = Field(default_factory=ShiftSchedule)


class CoverageReceipt(StrictMessage):
    receipt_id: Identifier
    run_id: Identifier
    bed_id: BedId
    start_ts: TimestampMs
    end_ts: TimestampMs
    state: Literal["trusted", "untrusted", "offline", "unknown"]
    source: Literal["backend", "local_lifecycle"]

    @model_validator(mode="after")
    def ordered(self) -> CoverageReceipt:
        if self.end_ts <= self.start_ts:
            raise ValueError("empty coverage interval")
        return self


class SuppressionReceipt(StrictMessage):
    receipt_id: Identifier
    run_id: Identifier
    bed_id: BedId
    alarm_id: Identifier
    ts: TimestampMs
    decision_id: Identifier
    source: Literal["decision", "backend"]


class Phase5Record(StrictMessage):
    model_config = ConfigDict(extra="forbid", frozen=False)
    schema_version: Literal[1] = 1
    run_id: Identifier
    revision: int = Field(ge=1, strict=True)
    as_of: TimestampMs


class ReportData(Phase5Record):
    incident_id: Identifier
    status: Literal[
        "draft", "needs_review", "ready_for_human_send", "human_marked_sent", "superseded"
    ]
    occurred_ts: TimestampMs | None
    observed_ts: TimestampMs
    noticed_ts: TimestampMs
    confirmed_ts: TimestampMs
    provisional_notice: bool
    notice_provenance: str
    deadline_ts: TimestampMs
    fields: dict[str, ReportField]
    missing_fields: list[str]
    evidence: list[dict[str, Any]]
    narrative: Narrative
    snapshot_id: Identifier
    human_edited: bool = False
    checklist: dict[str, bool]
    checked_revision: int | None = None
    sent: dict[str, Any] | None = None
    pdf: dict[str, Any] | None = None
    policy_note: str = (
        "DPDP breach-intimation Rule 7: eighteen-month commencement calculated as "
        "13 May 2027 from the 13 November 2025 notification; human applicability review required."
    )


class NurseLoad(StrictMessage):
    staff_id: StaffId
    count: int = Field(ge=0)
    overloaded: bool
    coverage: Literal["complete", "partial"]


class WorkloadData(Phase5Record):
    since: TimestampMs
    threshold: Literal[40] = 40
    comparator: Literal[">"] = ">"
    basis: Literal["distinct_screen_routed_alerts"] = "distinct_screen_routed_alerts"
    nurses: list[NurseLoad]
    unassigned_events: int = Field(ge=0)
    charge_nurse: StaffId | None
    notification: Literal["screen_routed", "not_required", "unresolved_roster"]
    roster_version: str | None


class BriefingData(Phase5Record):
    since: TimestampMs
    scope: Literal["demo_run", "configured_shift", "on_demand"]
    snapshot_id: Identifier
    facts: list[Fact]
    narrative: Narrative
    urgent: list[dict[str, Any]]
    status: Literal["ready", "superseded"] = "ready"


REPORT_FIELDS = (
    "reporter_name",
    "reporter_role",
    "organisation",
    "phone",
    "mobile",
    "email",
    "address",
    "affected_entity",
    "sector",
    "incident_type",
    "critical_to_mission",
    "ip_address",
    "hostname",
    "os_version",
    "last_patched",
    "vendor",
    "model",
    "location",
    "symptoms",
    "actions_taken",
    "evidence_summary",
)
