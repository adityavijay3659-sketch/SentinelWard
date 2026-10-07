from __future__ import annotations

import re
from collections.abc import Iterable

from sentinelward.contracts import VerdictMessage, timestamp_text

MAX_LINE_LENGTH = 160
WHITESPACE = re.compile(r"\s+")


def sanitize(value: object) -> str:
    return WHITESPACE.sub(" ", str(value)).strip()


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
