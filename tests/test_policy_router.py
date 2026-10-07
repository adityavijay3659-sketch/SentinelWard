from __future__ import annotations

from typing import Any

from sentinelward.contracts import ActionRequest, Verdict, VerdictMessage
from sentinelward.policy import authorize
from sentinelward.router import route_verdict


def verdict_fixture(contract_fixture: dict[str, Any], verdict: Verdict) -> VerdictMessage:
    raw = next(item for item in contract_fixture["verdicts"] if item["verdict"] == verdict)
    return VerdictMessage.model_validate(raw)


def test_emergency_routes_only_a1(contract_fixture: dict[str, Any]) -> None:
    requests = route_verdict(verdict_fixture(contract_fixture, Verdict.EMERGENCY))
    assert [(item.agent_id, item.action) for item in requests] == [("A1", "send_message")]


def test_both_fans_out_to_alert_and_containment(contract_fixture: dict[str, Any]) -> None:
    requests = route_verdict(verdict_fixture(contract_fixture, Verdict.BOTH))
    assert [(item.agent_id, item.action) for item in requests] == [
        ("A1", "send_message"),
        ("A2", "disable_client"),
    ]


def test_normal_has_no_actions(contract_fixture: dict[str, Any]) -> None:
    assert route_verdict(verdict_fixture(contract_fixture, Verdict.NORMAL)) == []


def test_unauthorized_cross_agent_action_is_denied() -> None:
    request = ActionRequest(
        correlation_id="B01:1:EMERGENCY",
        agent_id="A7",
        action="disable_client",
        target_id="MON-01",
    )
    decision = authorize(request)
    assert decision.allowed is False
    assert decision.code == "ACTION_NOT_ALLOWED"


def test_treatment_language_is_denied_even_for_allowed_action() -> None:
    request = ActionRequest(
        correlation_id="B01:1:EMERGENCY",
        agent_id="A1",
        action="send_message",
        target_id="B01",
        detail="administer medication now",
    )
    decision = authorize(request)
    assert decision.allowed is False
    assert decision.code == "TREATMENT_ACTION_PROHIBITED"


def test_it_only_undo_requires_role_and_identity() -> None:
    missing_role = ActionRequest(
        correlation_id="B01:1:TAMPERING",
        agent_id="A2",
        action="enable_client",
        target_id="MON-01",
    )
    assert authorize(missing_role).code == "IT_APPROVAL_REQUIRED"
