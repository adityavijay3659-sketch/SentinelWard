"""Deterministic one-line operational views; longer narrative stays separate."""

from sentinelward.contracts import RecordMessage
from sentinelward.phase5_contracts import BriefingData, ReportData, WorkloadData
from sentinelward.presentation import OutputViews, render_line


def record_views(record: RecordMessage) -> OutputViews:
    if record.kind == "report":
        report = ReportData.model_validate(record.data)
        fact = f"{len(report.missing_fields)} missing fields; revision {report.revision}"
        result = "HUMAN SEND ATTESTED" if report.sent else "HUMAN REVIEW AND SEND ONLY"
        event = "A5 REPORT"
    elif record.kind == "workload":
        workload = WorkloadData.model_validate(record.data)
        fact = f"{sum(n.overloaded for n in workload.nurses)} overloaded nurses; 2 h routed counts"
        result = (
            "CHARGE NURSE REVIEW"
            if any(n.overloaded for n in workload.nurses)
            else "WORKLOAD RECORDED"
        )
        event = "A7 WORKLOAD"
    else:
        briefing = BriefingData.model_validate(record.data)
        fact = f"{len(briefing.facts)} facts; {briefing.narrative.generator}"
        result = "URGENT: ACTIVE PATIENT ALERTS" if briefing.urgent else "BRIEFING READY"
        event = "A8 BRIEFING"
    line = render_line(
        timestamp_ms=record.ts, subject="WARD", source_event=event, key_fact=fact, result=result
    )
    return OutputViews(user=line, team=line, model=record.model_dump(mode="json"))
