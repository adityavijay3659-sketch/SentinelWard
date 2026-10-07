from __future__ import annotations

from dataclasses import dataclass, field

from sentinelward.contracts import ActionRequest, ActionResult


@dataclass(slots=True)
class SimulatedActionPort:
    """Safe Phase 1 adapter: records intent and performs no external control."""

    calls: list[ActionRequest] = field(default_factory=list)
    results: dict[str, ActionResult] = field(default_factory=dict)

    async def execute(self, request: ActionRequest, *, action_id: str) -> ActionResult:
        previous = self.results.get(request.idempotency_key)
        if previous is not None:
            return previous
        self.calls.append(request)
        result = ActionResult(
            action_id=action_id,
            idempotency_key=request.idempotency_key,
            status="completed",
            detail="Phase 1 simulated adapter recorded the authorized action",
            undo_available=request.action == "disable_client",
        )
        self.results[request.idempotency_key] = result
        return result
