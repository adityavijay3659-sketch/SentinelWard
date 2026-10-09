from __future__ import annotations

from typing import Any

from sentinelward.contracts import (
    ActionMessage,
    AlertMessage,
    BedsideCheckMessage,
    ScoreMessage,
    VerdictMessage,
)
from sentinelward.presentation import (
    MAX_LINE_LENGTH,
    alert_output_views,
    render_line,
    render_verdict,
    wire_output_views,
)


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


def test_alert_outputs_are_safe_for_users_diagnostic_for_team_and_structured_for_models(
    contract_fixture: dict[str, Any],
) -> None:
    message = AlertMessage.model_validate(contract_fixture["alert"])

    views = alert_output_views(message)

    assert views.user != views.team
    assert "staff:" not in views.user
    assert "EMERGENCY ALERT" in views.user
    assert views.user.endswith("RESPOND NOW")
    assert message.alert_id in views.team
    assert views.model == message.model_dump(mode="json")
    assert all("\n" not in value and len(value) <= MAX_LINE_LENGTH for value in views.lines())


def test_all_locked_phase_0_1_messages_have_distinct_bounded_human_and_model_views(
    contract_fixture: dict[str, Any],
) -> None:
    messages = [
        VerdictMessage.model_validate(contract_fixture["verdicts"][1]),
        ScoreMessage.model_validate(contract_fixture["m6_score"]),
        ActionMessage.model_validate(contract_fixture["action"]),
        AlertMessage.model_validate(contract_fixture["alert"]),
        BedsideCheckMessage.model_validate(contract_fixture["bedside_check"]),
    ]

    for message in messages:
        views = wire_output_views(message, ["A1"])
        assert views.user != views.team
        assert views.model == message.model_dump(mode="json")
        assert all(
            "\n" not in line and "\r" not in line and len(line) <= MAX_LINE_LENGTH
            for line in views.lines()
        )


def test_user_action_excludes_operator_details_and_does_not_imply_delivery() -> None:
    message = ActionMessage(
        v=1,
        type="action",
        action_id="act-test",
        ts=0,
        by="A1",
        action="send_message",
        bed_id="B01",
        detail="failed for staff:private_name",
        result="failed",
    )
    views = wire_output_views(message)
    assert "staff:" not in views.user and "private_name" not in views.user
    assert "staff:private_name" in views.team
    assert views.user.endswith("STAFF REVIEW NEEDED")
