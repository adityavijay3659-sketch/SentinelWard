from __future__ import annotations

from typing import Any

from sentinelward.contracts import VerdictMessage
from sentinelward.presentation import MAX_LINE_LENGTH, render_line, render_verdict


def test_verdict_output_is_one_bounded_line(contract_fixture: dict[str, Any]) -> None:
    message = VerdictMessage.model_validate(contract_fixture["verdicts"][3])
    line = render_verdict(message, ["A1", "A3"])
    assert "\n" not in line
    assert "\r" not in line
    assert len(line) <= MAX_LINE_LENGTH
    assert "VERDICT TAMPERING" in line
    assert line.endswith("A1+A3")


def test_untrusted_fact_is_truncated_before_identity_or_result() -> None:
    line = render_line(
        timestamp_ms=1_792_252_800_500,
        subject="B07",
        source_event="VERDICT TAMPERING 0.88",
        key_fact=("unsafe\ntext " * 100),
        result="A1 HAND-CHECK + A2 ISOLATE",
    )
    assert len(line) == MAX_LINE_LENGTH
    assert "\n" not in line
    assert "B07" in line
    assert line.endswith("A1 HAND-CHECK + A2 ISOLATE")
