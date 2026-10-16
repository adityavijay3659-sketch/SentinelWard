"""PDF export of an exact reviewed revision; never sends a report."""

from __future__ import annotations

import hashlib
import html
from io import BytesIO
from typing import Any

from sentinelward.phase5_contracts import ReportData


def export_pdf(report_id: str, report: ReportData) -> tuple[bytes, dict[str, Any]]:
    from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
    from reportlab.platypus import (  # type: ignore[import-untyped]
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    buffer = BytesIO()
    styles = getSampleStyleSheet()
    content: list[Any] = []

    def paragraph(text: str) -> None:
        content.append(Paragraph(html.escape(text), styles["BodyText"]))
        content.append(Spacer(1, 6))

    paragraph("SENTINELWARD — DRAFT / DEMO ONLY")
    paragraph(
        f"Report {report_id}; revision {report.revision}; generated at {report.as_of} UTC epoch ms"
    )
    paragraph("Human review required. This file is not a submission or proof of receipt.")
    paragraph(report.policy_note)
    paragraph(
        f"Notice time: {report.noticed_ts}; deadline: {report.deadline_ts}; "
        f"provisional: {report.provisional_notice}"
    )
    for name, field in report.fields.items():
        value = "MISSING — human input required" if field.value is None else str(field.value)
        paragraph(f"{name}: {value} ({field.status}; source: {field.source})")
    paragraph(f"Description ({report.narrative.generator}): {report.narrative.text}")
    for artifact in report.evidence:
        paragraph(
            f"Evidence: {artifact.get('kind', 'unknown')}; "
            f"available={artifact.get('available', False)}; "
            f"SHA-256={artifact.get('sha256', 'unavailable')}"
        )
    SimpleDocTemplate(buffer, title="SentinelWard draft report", author="SentinelWard").build(
        content
    )
    body = buffer.getvalue()
    return body, {
        "revision": report.revision,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "snapshot_hash": report.narrative.snapshot_hash,
    }
