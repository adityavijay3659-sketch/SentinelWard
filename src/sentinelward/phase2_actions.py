from __future__ import annotations

from dataclasses import dataclass

from sentinelward.alerts import AlertCoordinator
from sentinelward.contracts import ActionRequest, ActionResult
from sentinelward.ports import ActionPort


@dataclass(slots=True)
class Phase2ActionPort:
    alerts: AlertCoordinator
    fallback: ActionPort

    async def execute(self, request: ActionRequest, *, action_id: str) -> ActionResult:
        if request.agent_id != "A1" or request.action != "send_message":
            return await self.fallback.execute(request, action_id=action_id)
        if request.source_verdict is None:
            return ActionResult(
                action_id=action_id,
                idempotency_key=request.idempotency_key,
                status="failed",
                detail="A1 alert request has no source verdict",
            )
        alert = await self.alerts.handle_verdict(request.source_verdict)
        if alert is None:
            return ActionResult(
                action_id=action_id,
                idempotency_key=request.idempotency_key,
                status="completed",
                detail="A1 verdict required no nurse-facing alert",
            )
        return ActionResult(
            action_id=action_id,
            idempotency_key=request.idempotency_key,
            status="completed",
            detail=f"A1 alert {alert.alert_id} is {alert.status} at step {alert.ladder_step}",
            external_reference=alert.alert_id,
        )
