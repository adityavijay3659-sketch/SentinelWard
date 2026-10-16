from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sentinelward.contracts import (
    ActionMessage,
    AlertMessage,
    BedsideCheckMessage,
    DemoControlMessage,
    RecordMessage,
    RequestMessage,
    ScoreMessage,
    Verdict,
    VerdictMessage,
    VitalsMessage,
    WireMessage,
    timestamp_text,
)

MAX_LINE_LENGTH = 160
WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class OutputViews:
    user: str
    team: str
    model: dict[str, Any]

    def lines(self) -> tuple[str, str]:
        return (self.user, self.team)

    def as_dict(self) -> dict[str, object]:
        return {"user": self.user, "team": self.team, "model": self.model}


def sanitize(value: object) -> str:
    import unicodedata

    safe = "".join(" " if unicodedata.category(c).startswith("C") else c for c in str(value))
    return WHITESPACE.sub(" ", safe).strip()


def render_line(
    *, timestamp_ms: int, subject: str, source_event: str, key_fact: str, result: str
) -> str:
    fixed = [
        timestamp_text(timestamp_ms),
        sanitize(subject),
        sanitize(source_event).upper(),
        sanitize(key_fact),
        sanitize(result).upper(),
    ]
    line = " | ".join(fixed)
    if len(line) <= MAX_LINE_LENGTH:
        return line
    # Bound untrusted fixed fields too, preserving leading urgency and outcome.
    for index, limit in ((1, 22), (2, 48), (4, 38)):
        if len(fixed[index]) > limit:
            fixed[index] = fixed[index][: limit - 3].rstrip() + "..."
    non_fact_length = len(" | ".join([*fixed[:3], "", fixed[4]]))
    available = MAX_LINE_LENGTH - non_fact_length
    if available <= 3:
        fixed[3] = "..."
    else:
        fixed[3] = f"{fixed[3][: available - 3].rstrip()}..."
    return " | ".join(fixed)


def render_verdict(message: VerdictMessage, routed_agents: Iterable[str]) -> str:
    agents = "+".join(dict.fromkeys(routed_agents)) or "NO ACTION"
    fact = "; ".join(message.reasons)
    return render_line(
        timestamp_ms=message.ts,
        subject=message.bed_id,
        source_event=f"VERDICT {message.verdict.value} {message.confidence:.2f}",
        key_fact=fact,
        result=agents,
    )


def render_alert(message: AlertMessage) -> str:
    recipient = ",".join(message.to) if message.to else "PHONE PENDING"
    ack = f"ACK {message.acked_by}" if message.acked_by else message.status
    return render_line(
        timestamp_ms=message.ts,
        subject=message.bed_id,
        source_event=f"A1 {message.verdict.value} STEP {message.ladder_step}",
        key_fact=f"{message.alert_id}; to={recipient}; {message.text}",
        result=ack,
    )


def render_user_alert(message: AlertMessage) -> str:
    if message.status == "acknowledged":
        result = "ACKNOWLEDGED"
    elif message.status == "escalated":
        result = "ESCALATED"
    elif message.priority == "high":
        result = "RESPOND NOW"
    else:
        result = "CHECK PATIENT"
    return render_line(
        timestamp_ms=message.ts,
        subject=message.bed_id,
        source_event=user_event_label(message.verdict),
        key_fact=message.text,
        result=result,
    )


def render_score(message: ScoreMessage) -> str:
    event = (
        "URGENT M6 PATIENT CHECK"
        if message.model == "M6" and message.label == "emergency_compatible"
        else f"M6 GAP-ONLY {message.label} {message.score:.2f}"
        if message.model == "M6" and message.extra.get("assessment_path") == "cuff_gap_only"
        else f"{message.model} {message.label} {message.score:.2f}"
    )
    return render_line(
        timestamp_ms=message.window_start,
        subject=message.bed_id,
        source_event=event,
        key_fact=message.reason,
        result="RESEARCH ONLY" if message.extra.get("mode") == "research" else "MODEL OUTPUT",
    )


def render_user_score(message: ScoreMessage) -> str:
    return render_line(
        timestamp_ms=message.window_start,
        subject=message.bed_id,
        source_event=(
            "URGENT: PATIENT CHECK"
            if message.label == "emergency_compatible"
            else "WARNING: PRESSURE GAP"
            if message.model == "M6"
            and message.label == "insufficient_data"
            and message.extra.get("assessment_path") == "cuff_gap_only"
            else "WARNING: DATA MISSING"
            if message.label == "insufficient_data"
            else "WARNING: POSSIBLE DRIFT"
            if message.label == "drift"
            else "SENSOR ASSESSMENT"
        ),
        key_fact=message.reason,
        result="RESEARCH; STAFF REVIEW"
        if message.extra.get("mode") == "research"
        else "STAFF REVIEW",
    )


def render_action(message: ActionMessage) -> str:
    subject = message.device_id or message.bed_id or message.action_id
    result = {
        "ok": "COMPLETE",
        "failed": "FAILED",
        "pending": "PENDING",
        "unknown": "HUMAN REVIEW",
    }[message.result]
    if message.undo_id is not None:
        result = f"{result}; UNDO AVAILABLE"
    return render_line(
        timestamp_ms=message.ts,
        subject=subject,
        source_event=f"{message.by} {message.action}",
        key_fact=message.detail,
        result=result,
    )


def render_user_action(message: ActionMessage) -> str:
    subject = message.device_id or message.bed_id or "WARD"
    result = {
        "ok": "COMPLETED",
        "failed": "STAFF REVIEW NEEDED",
        "pending": "IN PROGRESS",
        "unknown": "STATUS CHECK NEEDED",
    }[message.result]
    fact = {
        "send_message": "Phone backup delivery",
        "edit_message": "Phone backup message update",
        "record_ack": "Staff acknowledgement",
        "escalate": "Alert escalation",
        "disable_client": "Device connection isolation",
        "restore_client": "Device connection restoration",
    }.get(message.action, "Automation action status")
    return render_line(
        timestamp_ms=message.ts,
        subject=subject,
        source_event="SYSTEM UPDATE",
        key_fact=fact,
        result=result,
    )


def render_bedside(message: BedsideCheckMessage) -> str:
    return render_line(
        timestamp_ms=message.ts,
        subject=message.bed_id,
        source_event=f"BEDSIDE {message.result}",
        key_fact=f"confirmed by {message.by}",
        result="CHECK REPORTED",
    )


def render_user_bedside(message: BedsideCheckMessage) -> str:
    result = "CHECK REPORTED" if message.result == "patient_ok" else "URGENT: CHECK REPORTED"
    return render_line(
        timestamp_ms=message.ts,
        subject=message.bed_id,
        source_event="PATIENT CHECK",
        key_fact=message.result.replace("_", " "),
        result=result,
    )


def render_user_verdict(message: VerdictMessage) -> str:
    result = {
        Verdict.NORMAL: "NO ACTION",
        Verdict.EMERGENCY: "RESPOND NOW",
        Verdict.BOTH: "RESPOND NOW",
        Verdict.TAMPERING: "CHECK PATIENT BY HAND",
        Verdict.UNSURE: "CHECK PATIENT BY HAND",
        Verdict.DRIFTING: "BIOMED CHECK",
        Verdict.LOOSE_SENSOR: "REFIT SENSOR",
        Verdict.DEVICE_ATTACK: "IT REVIEW",
    }[message.verdict]
    return render_line(
        timestamp_ms=message.ts,
        subject=message.bed_id,
        source_event=user_event_label(message.verdict),
        key_fact="; ".join(message.reasons),
        result=result,
    )


def user_event_label(verdict: Verdict) -> str:
    return {
        Verdict.NORMAL: "NORMAL",
        Verdict.EMERGENCY: "EMERGENCY ALERT",
        Verdict.BOTH: "EMERGENCY + SECURITY",
        Verdict.TAMPERING: "WARNING: UNTRUSTED MONITOR",
        Verdict.UNSURE: "WARNING: CHECK NEEDED",
        Verdict.DRIFTING: "WARNING: SENSOR DRIFT",
        Verdict.LOOSE_SENSOR: "SENSOR NOTICE",
        Verdict.DEVICE_ATTACK: "SECURITY WARNING",
    }[verdict]


def wire_output_views(message: WireMessage, routed_agents: Iterable[str] = ()) -> OutputViews:
    if (
        isinstance(message, RecordMessage)
        and message.kind in {"report", "workload", "briefing"}
        and message.data.get("schema_version") == 1
    ):
        from sentinelward.phase5_presentation import record_views

        return record_views(message)
    if isinstance(message, AlertMessage):
        user = render_user_alert(message)
        team = render_alert(message)
    elif isinstance(message, VerdictMessage):
        user = render_user_verdict(message)
        team = render_verdict(message, routed_agents)
    elif isinstance(message, ScoreMessage):
        user = render_user_score(message)
        team = render_score(message)
    elif isinstance(message, ActionMessage):
        user = render_user_action(message)
        team = render_action(message)
    elif isinstance(message, VitalsMessage):
        user = render_line(
            timestamp_ms=message.ts,
            subject=message.bed_id,
            source_event="MONITOR DATA",
            key_fact="Readings received",
            result="AWAITING ASSESSMENT",
        )
        team = render_line(
            timestamp_ms=message.ts,
            subject=message.bed_id,
            source_event="VITALS",
            key_fact=f"{message.device_id}; seq={message.seq}; fs={message.fs}",
            result="RECEIVED",
        )
    elif isinstance(message, BedsideCheckMessage):
        user = render_user_bedside(message)
        team = render_bedside(message)
    else:
        subject = "WARD"
        event: str
        fact: str
        result: str
        if isinstance(message, DemoControlMessage):
            event, fact, result = "DEMO CONTROL", message.cmd, "REQUEST RECEIVED"
        elif isinstance(message, RequestMessage):
            subject = message.bed_id or "WARD"
            event, fact, result = "STAFF REQUEST", message.action, "REQUEST RECEIVED"
        elif isinstance(message, RecordMessage):
            event, fact, result = "AGENT RECORD", message.kind, "RECORD RECEIVED"
        user = render_line(
            timestamp_ms=message.ts,
            subject=subject,
            source_event=event,
            key_fact=fact,
            result=result,
        )
        team = user
    return OutputViews(user=user, team=team, model=message.model_dump(mode="json"))


def alert_output_views(message: AlertMessage) -> OutputViews:
    return wire_output_views(message)
