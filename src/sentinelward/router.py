from __future__ import annotations

from sentinelward.contracts import ActionRequest, Verdict, VerdictMessage, correlation_id_for


def _device_for_bed(bed_id: str) -> str:
    return f"MON-{bed_id[1:]}"


def route_verdict(message: VerdictMessage) -> list[ActionRequest]:
    correlation_id = correlation_id_for(message)
    device_id = _device_for_bed(message.bed_id)

    def request(agent_id: str, action: str, target: str, detail: str) -> ActionRequest:
        return ActionRequest(
            correlation_id=correlation_id,
            agent_id=agent_id,
            action=action,
            target_id=target,
            bed_id=message.bed_id,
            device_id=device_id,
            detail=detail,
        )

    routes: dict[Verdict, list[ActionRequest]] = {
        Verdict.NORMAL: [],
        Verdict.EMERGENCY: [
            request("A1", "send_message", message.bed_id, "possible clinical emergency")
        ],
        Verdict.BOTH: [
            request("A1", "send_message", message.bed_id, "emergency remains possible"),
            request("A2", "disable_client", device_id, "contain compromised monitor client"),
        ],
        Verdict.TAMPERING: [
            request("A1", "send_message", message.bed_id, "bedside hand-check required"),
            request("A3", "snapshot_files", device_id, "preserve tampering evidence"),
        ],
        Verdict.UNSURE: [
            request("A1", "send_message", message.bed_id, "bedside hand-check required")
        ],
        Verdict.DRIFTING: [
            request("A1", "send_message", message.bed_id, "sensor drift needs bedside review"),
            request("A6", "open_ticket", device_id, "open biomed drift ticket"),
        ],
        Verdict.LOOSE_SENSOR: [
            request("A1", "send_message", message.bed_id, "refit the loose sensor")
        ],
        Verdict.DEVICE_ATTACK: [
            request("A3", "snapshot_files", device_id, "preserve device attack evidence")
        ],
    }
    return routes[message.verdict]
