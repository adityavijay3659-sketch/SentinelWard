from __future__ import annotations

import json
from typing import Any

import pytest

from sentinelward.contracts import (
    ActionMessage,
    AlertMessage,
    BedsideCheckMessage,
    ScoreMessage,
    VerdictMessage,
    ingress_idempotency_key,
    parse_wire_message,
)
from sentinelward.errors import ContractError


def encoded(value: dict[str, Any]) -> bytes:
    return json.dumps(value).encode()


def test_all_verdict_fixtures_validate(contract_fixture: dict[str, Any]) -> None:
    for raw in contract_fixture["verdicts"]:
        message = VerdictMessage.model_validate(raw)
        parsed = parse_wire_message(f"ward/bed/{message.bed_id}/verdict", encoded(raw))
        assert parsed == message
        assert ingress_idempotency_key(message).startswith(f"{message.bed_id}:")


def test_other_locked_message_fixtures_validate(contract_fixture: dict[str, Any]) -> None:
    score = ScoreMessage.model_validate(contract_fixture["m6_score"])
    action = ActionMessage.model_validate(contract_fixture["action"])
    alert = AlertMessage.model_validate(contract_fixture["alert"])
    bedside = BedsideCheckMessage.model_validate(contract_fixture["bedside_check"])

    assert (
        parse_wire_message(
            f"ward/bed/{score.bed_id}/score/M6", encoded(contract_fixture["m6_score"])
        )
        == score
    )
    assert parse_wire_message("ward/action", encoded(contract_fixture["action"])) == action
    assert parse_wire_message("ward/alert", encoded(contract_fixture["alert"])) == alert
    assert (
        parse_wire_message(
            f"ward/bed/{bedside.bed_id}/bedside", encoded(contract_fixture["bedside_check"])
        )
        == bedside
    )


@pytest.mark.parametrize(
    ("topic", "payload", "code"),
    [
        ("ward/bed/B01/verdict", b"not-json", "INVALID_JSON"),
        ("ward/unknown", b"{}", "UNKNOWN_TOPIC"),
        (
            "ward/bed/B01/verdict",
            b'{"v":1,"type":"score"}',
            "TOPIC_TYPE_MISMATCH",
        ),
    ],
)
def test_invalid_input_has_stable_error_code(topic: str, payload: bytes, code: str) -> None:
    with pytest.raises(ContractError) as captured:
        parse_wire_message(topic, payload)
    assert captured.value.code == code


def test_topic_bed_must_match_payload(contract_fixture: dict[str, Any]) -> None:
    raw = contract_fixture["verdicts"][0]
    with pytest.raises(ContractError) as captured:
        parse_wire_message("ward/bed/B02/verdict", encoded(raw))
    assert captured.value.code == "BED_TOPIC_MISMATCH"


def test_payload_limit_is_enforced() -> None:
    with pytest.raises(ContractError) as captured:
        parse_wire_message("ward/bed/B01/verdict", b"x" * 10, max_bytes=5)
    assert captured.value.code == "PAYLOAD_TOO_LARGE"


def test_priority_must_match_verdict(contract_fixture: dict[str, Any]) -> None:
    raw = dict(contract_fixture["verdicts"][1])
    raw["priority"] = "low"
    with pytest.raises(ValueError, match="does not match"):
        VerdictMessage.model_validate(raw)


def test_alert_ladder_is_strictly_limited_to_three_steps(
    contract_fixture: dict[str, Any],
) -> None:
    raw = dict(contract_fixture["alert"])
    raw["ladder_step"] = 4
    with pytest.raises(ValueError):
        AlertMessage.model_validate(raw)


def test_bedside_result_rejects_unlocked_aliases(contract_fixture: dict[str, Any]) -> None:
    raw = dict(contract_fixture["bedside_check"])
    raw["result"] = "patient_safe"
    with pytest.raises(ValueError):
        BedsideCheckMessage.model_validate(raw)
