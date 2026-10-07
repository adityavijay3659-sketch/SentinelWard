from __future__ import annotations

from dataclasses import dataclass

from sentinelward.contracts import ActionRequest

AGENT_ACTIONS: dict[str, frozenset[str]] = {
    "A1": frozenset({"send_message", "edit_message", "escalate", "record_ack"}),
    "A2": frozenset({"disable_client", "set_bed_untrusted", "enable_client"}),
    "A3": frozenset({"snapshot_files", "hash_file", "write_timeline"}),
    "A4": frozenset({"list_devices", "set_watch_level"}),
    "A5": frozenset({"draft_report", "start_clock"}),
    "A6": frozenset({"open_ticket", "update_ticket"}),
    "A7": frozenset({"warn_workload"}),
    "A8": frozenset({"write_briefing"}),
    "A9": frozenset(),
}

IT_ONLY_ACTIONS = frozenset({"enable_client"})
PROHIBITED_TERMS = frozenset(
    {"administer", "dose", "infuse", "medication", "pump", "treatment", "ventilator"}
)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    code: str
    detail: str


def authorize(request: ActionRequest) -> PolicyDecision:
    allowed = AGENT_ACTIONS.get(request.agent_id, frozenset())
    if request.action not in allowed:
        return PolicyDecision(False, "ACTION_NOT_ALLOWED", "agent action is not allow-listed")
    searchable = f"{request.action} {request.detail}".lower()
    if any(term in searchable for term in PROHIBITED_TERMS):
        return PolicyDecision(
            False, "TREATMENT_ACTION_PROHIBITED", "treatment control is prohibited"
        )
    if request.action in IT_ONLY_ACTIONS and request.requested_by_role != "it":
        return PolicyDecision(
            False, "IT_APPROVAL_REQUIRED", "action requires authenticated IT role"
        )
    if request.action == "enable_client" and request.approved_by is None:
        return PolicyDecision(False, "APPROVER_REQUIRED", "undo requires an approving identity")
    return PolicyDecision(True, "ALLOWED", "action is authorized")
