from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints, model_validator

from sentinelward.errors import ContractError

BedId = Annotated[str, StringConstraints(pattern=r"^B(?:0[1-9]|1[0-2])$")]
DeviceId = Annotated[str, StringConstraints(pattern=r"^MON-(?:0[1-9]|1[0-2])$")]
StaffId = Annotated[str, StringConstraints(pattern=r"^staff:[a-z][a-z0-9_-]{0,31}$")]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=96)]
Reason = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]
TimestampMs = Annotated[int, Field(ge=0, le=253_402_300_799_999)]


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CuffReading(StrictMessage):
    sys: FiniteFloat
    dia: FiniteFloat
    map: FiniteFloat
    ts: TimestampMs

    @model_validator(mode="after")
    def ordered(self) -> CuffReading:
        if not 0 < self.dia <= self.map <= self.sys <= 350:
            raise ValueError("cuff pressures must satisfy 0 < dia <= map <= sys <= 350")
        return self


class MonitorAlarm(StrictMessage):
    code: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    priority: Literal["low", "medium", "high"]


Waveform = Annotated[list[FiniteFloat], Field(min_length=125, max_length=125)]


class VitalsMessage(StrictMessage):
    v: Literal[1]
    type: Literal["vitals"]
    bed_id: BedId
    device_id: DeviceId
    seq: Annotated[int, Field(ge=0)]
    ts: TimestampMs
    fs: Literal[125]
    ecg: Waveform | None
    ppg: Waveform | None
    abp: Waveform | None
    hr: FiniteFloat | None
    spo2: FiniteFloat | None
    rr: FiniteFloat | None
    nibp: CuffReading | None
    monitor_alarm: MonitorAlarm | None

    @model_validator(mode="after")
    def causal(self) -> VitalsMessage:
        if self.ts % 1000:
            raise ValueError("vitals ts must identify the start of a whole one-second frame")
        if self.nibp is not None and self.nibp.ts > self.ts:
            raise ValueError("cuff reading cannot come from the future")
        return self


class Verdict(StrEnum):
    NORMAL = "NORMAL"
    EMERGENCY = "EMERGENCY"
    BOTH = "BOTH"
    TAMPERING = "TAMPERING"
    UNSURE = "UNSURE"
    DRIFTING = "DRIFTING"
    LOOSE_SENSOR = "LOOSE_SENSOR"
    DEVICE_ATTACK = "DEVICE_ATTACK"


EXPECTED_PRIORITY: dict[Verdict, str] = {
    Verdict.NORMAL: "none",
    Verdict.EMERGENCY: "high",
    Verdict.BOTH: "high",
    Verdict.TAMPERING: "medium",
    Verdict.UNSURE: "medium",
    Verdict.DRIFTING: "medium",
    Verdict.LOOSE_SENSOR: "low",
    Verdict.DEVICE_ATTACK: "none",
}


class VerdictMessage(StrictMessage):
    v: Literal[1]
    type: Literal["verdict"]
    bed_id: BedId
    ts: TimestampMs
    window_start: TimestampMs
    verdict: Verdict
    priority: Literal["none", "low", "medium", "high"]
    confidence: Probability
    trust: Probability
    last_trusted_ts: TimestampMs | None
    reasons: Annotated[list[Reason], Field(min_length=1, max_length=3)]
    scores: dict[Annotated[str, StringConstraints(pattern=r"^M[1-6]$")], Probability]

    @model_validator(mode="after")
    def validate_verdict(self) -> VerdictMessage:
        if self.priority != EXPECTED_PRIORITY[self.verdict]:
            raise ValueError(f"priority {self.priority!r} does not match {self.verdict}")
        if self.window_start > self.ts:
            raise ValueError("window_start cannot be after ts")
        return self


class ScoreMessage(StrictMessage):
    v: Literal[1]
    type: Literal["score"]
    bed_id: BedId
    model: Annotated[str, StringConstraints(pattern=r"^M[1-6]$")]
    model_version: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    window_start: TimestampMs
    window_s: Annotated[int, Field(gt=0, le=300)]
    score: Probability
    label: Annotated[str, StringConstraints(min_length=1, max_length=48)]
    reason: Reason
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def finite_json_metadata(self) -> ScoreMessage:
        try:
            json.dumps(self.extra, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("score metadata must contain finite JSON values") from exc
        return self


class ActionMessage(StrictMessage):
    v: Literal[1]
    type: Literal["action"]
    action_id: Identifier
    ts: TimestampMs
    by: Annotated[str, StringConstraints(pattern=r"^A[1-9]$")]
    action: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    bed_id: BedId | None = None
    device_id: DeviceId | None = None
    detail: Annotated[str, StringConstraints(max_length=240)]
    undo_id: Identifier | None = None
    undoes: Identifier | None = None
    approved_by: StaffId | None = None
    result: Literal["ok", "failed", "pending", "unknown"]


class AlertMessage(StrictMessage):
    v: Literal[1]
    type: Literal["alert"]
    alert_id: Identifier
    ts: TimestampMs
    bed_id: BedId
    verdict: Verdict
    priority: Literal["low", "medium", "high"]
    text: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    to: list[StaffId]
    ladder_step: Annotated[int, Field(ge=1, le=3)]
    status: Literal["open", "escalated", "acknowledged", "failed"]
    acked_by: StaffId | None = None
    acked_ts: TimestampMs | None = None


class BedsideCheckMessage(StrictMessage):
    v: Literal[1]
    type: Literal["bedside_check"]
    bed_id: BedId
    ts: TimestampMs
    result: Literal["patient_ok", "patient_not_ok"]
    by: StaffId


class AgentEventEnvelope(StrictMessage):
    v: Literal[1]
    event_id: Identifier
    event_type: Annotated[
        str,
        StringConstraints(
            pattern=r"^(?:ticket|report|workload|briefing|workflow)\.[a-z][a-z0-9_]*$"
        ),
    ]
    ts: TimestampMs
    source_agent: Annotated[str, StringConstraints(pattern=r"^A[1-9]$")]
    bed_id: BedId | None = None
    device_id: DeviceId | None = None
    correlation_id: Identifier
    payload: dict[str, Any]


class V11Message(StrictMessage):
    @model_validator(mode="before")
    @classmethod
    def strict_version(cls, value: Any) -> Any:
        if isinstance(value, dict) and (type(value.get("v")) is not int or value.get("v") != 1):
            raise ValueError("v1.1 message v must be integer 1")
        return value


class DemoControlMessage(V11Message):
    """Doc 00 v1.1: backend-owned control, authenticated by broker ACL."""

    v: Literal[1]
    type: Literal["demo_control"]
    ts: TimestampMs
    cmd: Literal["run", "reset"]
    run_id: Identifier
    start_at_s: Annotated[int, Field(ge=0, lt=1200, strict=True)] = 0


class RequestMessage(V11Message):
    v: Literal[1]
    type: Literal["request"]
    request_id: Identifier
    ts: TimestampMs
    by: StaffId
    action: Literal["ack_alert", "escalate_alert", "isolate_device", "undo_action"]
    target_id: Identifier
    bed_id: BedId | None = None
    note: Annotated[str, StringConstraints(max_length=240)] = ""


class RecordMessage(V11Message):
    v: Literal[1]
    type: Literal["record"]
    ts: TimestampMs
    kind: Literal["incident", "report", "ticket", "workload", "briefing"]
    record_id: Identifier
    by: Literal["A3", "A5", "A6", "A7", "A8"]
    data: dict[str, Any]

    @model_validator(mode="after")
    def owned_finite_record(self) -> RecordMessage:
        owners = {
            "incident": "A3",
            "report": "A5",
            "ticket": "A6",
            "workload": "A7",
            "briefing": "A8",
        }
        if self.by != owners[self.kind]:
            raise ValueError("record kind does not match its owning agent")
        if self.kind == "incident" and not isinstance(self.data.get("evidence"), list):
            raise ValueError("incident data.evidence must be a list")
        json.dumps(self.data, allow_nan=False)
        return self


class DemoSourceEnd(V11Message):
    """Trusted internal lifecycle callback; not a new locked MQTT topic."""

    v: Literal[1]
    type: Literal["demo_source_end"]
    run_id: Identifier
    ts: TimestampMs
    bed_id: BedId
    device_id: DeviceId
    source: Literal["simulator", "backend"]
    reason: Literal["recording_complete"]


class ActionRequest(StrictMessage):
    correlation_id: Identifier
    agent_id: Annotated[str, StringConstraints(pattern=r"^A[1-9]$")]
    action: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    target_id: Identifier
    bed_id: BedId | None = None
    device_id: DeviceId | None = None
    detail: Annotated[str, StringConstraints(max_length=240)] = ""
    requested_by_role: Annotated[str, StringConstraints(min_length=1, max_length=32)] = "system"
    approved_by: StaffId | None = None
    source_verdict: VerdictMessage | None = None

    @property
    def idempotency_key(self) -> str:
        return f"{self.correlation_id}:{self.agent_id}:{self.action}:{self.target_id}"


class ActionResult(StrictMessage):
    action_id: Identifier
    idempotency_key: Identifier
    status: Literal["completed", "rejected", "failed", "unknown"]
    detail: Annotated[str, StringConstraints(max_length=240)]
    external_reference: Identifier | None = None
    undo_available: bool = False


type WireMessage = (
    VerdictMessage
    | ScoreMessage
    | ActionMessage
    | AlertMessage
    | BedsideCheckMessage
    | VitalsMessage
    | DemoControlMessage
    | RequestMessage
    | RecordMessage
)

BED_TOPIC = re.compile(
    r"^ward/bed/(?P<bed>B(?:0[1-9]|1[0-2]))/(?P<kind>verdict|bedside|vitals|score/M[1-6])$"
)


def parse_wire_message(topic: str, payload: bytes, *, max_bytes: int = 65_536) -> WireMessage:
    if len(payload) > max_bytes:
        raise ContractError("PAYLOAD_TOO_LARGE", f"payload is {len(payload)} bytes")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("INVALID_JSON", str(exc)) from exc
    if not isinstance(value, dict):
        raise ContractError("INVALID_SHAPE", "wire payload must be a JSON object")

    message_type = value.get("type")
    match: re.Match[str] | None = None
    model: type[StrictMessage]
    if topic == "ward/action":
        model = ActionMessage
        expected_type = "action"
    elif topic == "ward/alert":
        model = AlertMessage
        expected_type = "alert"
    elif topic == "ward/demo/control":
        model = DemoControlMessage
        expected_type = "demo_control"
    elif topic == "ward/request":
        model = RequestMessage
        expected_type = "request"
    elif topic == "ward/record":
        model = RecordMessage
        expected_type = "record"
    else:
        match = BED_TOPIC.fullmatch(topic)
        if match is None:
            raise ContractError("UNKNOWN_TOPIC", topic)
        kind = match.group("kind")
        expected_type = {"verdict": "verdict", "bedside": "bedside_check", "vitals": "vitals"}.get(
            kind, "score"
        )
        if kind == "vitals":
            model = VitalsMessage
        elif kind == "verdict":
            model = VerdictMessage
        elif kind == "bedside":
            model = BedsideCheckMessage
        else:
            model = ScoreMessage

    if message_type != expected_type:
        raise ContractError(
            "TOPIC_TYPE_MISMATCH", f"topic expects {expected_type!r}, got {message_type!r}"
        )
    try:
        parsed = model.model_validate(value)
    except Exception as exc:
        raise ContractError("SCHEMA_INVALID", str(exc)) from exc

    wire_message = parsed
    match = BED_TOPIC.fullmatch(topic)
    if match and hasattr(wire_message, "bed_id") and wire_message.bed_id != match.group("bed"):
        raise ContractError("BED_TOPIC_MISMATCH", "topic bed does not match payload bed_id")
    if isinstance(wire_message, ScoreMessage) and not topic.endswith(f"score/{wire_message.model}"):
        raise ContractError("MODEL_TOPIC_MISMATCH", "topic model does not match payload model")
    return wire_message


def correlation_id_for(message: WireMessage) -> str:
    if isinstance(message, DemoControlMessage):
        return f"demo:{payload_sha256(message.model_dump_json().encode())}"
    if isinstance(message, RequestMessage):
        return message.request_id
    if isinstance(message, RecordMessage):
        digest = payload_sha256(message.model_dump_json().encode())
        return f"record:{message.record_id}:{message.ts}:{digest}"
    if isinstance(message, VitalsMessage):
        return f"{message.bed_id}:{message.device_id}:{message.ts}:{message.seq}:vitals"
    if isinstance(message, VerdictMessage):
        return f"{message.bed_id}:{message.window_start}:{message.verdict.value}"
    if isinstance(message, ScoreMessage):
        return f"{message.bed_id}:{message.window_start}:{message.model}"
    if isinstance(message, AlertMessage):
        return message.alert_id
    if isinstance(message, ActionMessage):
        return message.action_id
    return f"{message.bed_id}:{message.ts}:bedside"


def ingress_idempotency_key(message: WireMessage) -> str:
    return correlation_id_for(message)


def payload_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def timestamp_text(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%H:%M:%S UTC")
