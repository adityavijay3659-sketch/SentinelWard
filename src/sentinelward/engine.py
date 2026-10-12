from __future__ import annotations

from typing import Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sentinelward.contracts import ActionRequest, ActionResult, VerdictMessage
from sentinelward.phase4 import Phase4Coordinator
from sentinelward.policy import authorize
from sentinelward.ports import ActionPort, FoundationStore
from sentinelward.router import route_verdict


class WorkflowState(TypedDict, total=False):
    verdict: dict[str, Any]
    action_requests: list[dict[str, Any]]
    results: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    terminal_status: str


class AutomationEngine:
    def __init__(
        self,
        *,
        store: FoundationStore,
        action_port: ActionPort,
        checkpointer: Any | None = None,
        phase4: Phase4Coordinator | None = None,
    ) -> None:
        self._store = store
        self._action_port = action_port
        self._phase4 = phase4
        builder = StateGraph(WorkflowState)
        builder.add_node("route", self._route_node)
        builder.add_node("authorize_and_execute", self._execute_node)
        if phase4 is not None:
            builder.add_node("phase4", self._phase4_node)
        builder.add_edge(START, "route")
        builder.add_edge("route", "authorize_and_execute")
        if phase4 is not None:
            builder.add_edge("authorize_and_execute", "phase4")
            builder.add_edge("phase4", END)
        else:
            builder.add_edge("authorize_and_execute", END)
        self.graph: CompiledStateGraph[Any, Any, Any, Any] = builder.compile(
            checkpointer=checkpointer
        )

    async def run(self, message: VerdictMessage, *, thread_id: str) -> WorkflowState:
        if self._phase4 is not None:
            async with self._phase4.lifecycle_gate:
                await self._phase4.validate_verdict(message)
                return await self._run_graph(message, thread_id=thread_id)
        return await self._run_graph(message, thread_id=thread_id)

    async def _run_graph(self, message: VerdictMessage, *, thread_id: str) -> WorkflowState:
        state: WorkflowState = {"verdict": message.model_dump(mode="json")}
        result = await self.graph.ainvoke(
            state,
            config={"configurable": {"thread_id": thread_id}},
        )
        return cast(WorkflowState, result)

    async def _route_node(self, state: WorkflowState) -> WorkflowState:
        verdict = VerdictMessage.model_validate(state["verdict"])
        requests = route_verdict(verdict)
        if self._phase4 is not None:
            requests = [request for request in requests if request.agent_id == "A1"]
        return {"action_requests": [item.model_dump(mode="json") for item in requests]}

    async def _execute_node(self, state: WorkflowState) -> WorkflowState:
        results: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for raw in state.get("action_requests", []):
            request = ActionRequest.model_validate(raw)
            decision = authorize(request)
            await self._store.append_audit(
                correlation_id=request.correlation_id,
                event_type="policy.allowed" if decision.allowed else "policy.rejected",
                actor=request.agent_id,
                detail={"action": request.action, "code": decision.code},
            )
            if not decision.allowed:
                rejected.append({"request": raw, "code": decision.code})
                continue
            action_id, created = await self._store.reserve_action(request)
            if not created:
                if request.agent_id == "A1" and request.action == "send_message":
                    result = await self._call_action(request, action_id)
                    await self._store.complete_action(result)
                    await self._store.append_audit(
                        correlation_id=request.correlation_id,
                        event_type=f"action.{result.status}",
                        actor=request.agent_id,
                        detail=result.model_dump(mode="json"),
                    )
                    results.append(result.model_dump(mode="json"))
                    continue
                results.append(
                    {
                        "action_id": action_id,
                        "idempotency_key": request.idempotency_key,
                        "status": "duplicate",
                    }
                )
                continue
            result = await self._call_action(request, action_id)
            await self._store.complete_action(result)
            await self._store.append_audit(
                correlation_id=request.correlation_id,
                event_type=f"action.{result.status}",
                actor=request.agent_id,
                detail=result.model_dump(mode="json"),
            )
            results.append(result.model_dump(mode="json"))
        terminal = "completed" if not rejected else "rejected"
        return {"results": results, "rejected": rejected, "terminal_status": terminal}

    async def _call_action(self, request: ActionRequest, action_id: str) -> ActionResult:
        try:
            return await self._action_port.execute(request, action_id=action_id)
        except Exception:
            if self._phase4 is None:
                raise
            return ActionResult(
                action_id=action_id,
                idempotency_key=request.idempotency_key,
                status="unknown",
                detail="A1 effect outcome uncertain; action audit retained",
            )

    async def _phase4_node(self, state: WorkflowState) -> WorkflowState:
        assert self._phase4 is not None
        message = VerdictMessage.model_validate(state["verdict"])
        effects = await self._phase4.handle_verdict(message)
        results = list(state.get("results", []))
        results.extend(effects)
        failed = any(e["status"] in {"unknown", "failed", "pending"} for e in effects)
        failed = failed or any(
            e.get("status") in {"unknown", "failed", "pending"} for e in state.get("results", [])
        )
        return {
            "results": results,
            "terminal_status": "failed" if failed else state.get("terminal_status", "completed"),
        }
