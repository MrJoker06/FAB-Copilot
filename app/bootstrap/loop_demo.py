"""Run a fixed two-response model fixture through one Loop Dispatcher round."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import date

from ..agent_runtime.definition import AgentDefinition, ComponentReference
from ..agent_runtime.execution.loop_dispatch import execute_dispatched_loop_round
from ..agent_runtime.execution.loop_guard import ToolLoopGuard
from ..agent_runtime.execution.loop_response import classify_loop_response
from ..agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from ..agent_runtime.execution.runtime_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
)
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.contracts import ToolExecutionLimits, ToolStatus
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from ..manufacturing.equipment_health.binding import create_equipment_health_binding
from .agent_assembly import AssemblyError, assemble_agent
from .dispatcher_demo import _fake
from .loop_assembly import bind_loop_run
from .ready_demo import _agent_parser, _Events, _Principal, _ready_plan


@dataclass(slots=True)
class _TwoResponseModel:
    """The first response selects a tool; the second consumes its tool message."""

    tool: str
    arguments: str
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(
        self, request: ModelRequest, _context: RuntimeContext
    ) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=(ModelToolCall("model-health-1", self.tool, self.arguments),)
            )
        if len(self.requests) == 2 and any(
            message.role == "tool" and message.tool_call_id == "model-health-1"
            for message in request.messages
        ):
            return ModelResponse(content="Fixed Loop fixture completed.")
        raise AssertionError("unexpected Loop model sequence")


def _parser() -> argparse.ArgumentParser:
    parser = _agent_parser()
    parser.description = __doc__
    return parser


def _typed_result(result: object) -> dict[str, object]:
    return {
        "call_id": result.call_id,
        "tool": result.tool_name,
        "version": result.tool_version,
        "status": result.status.value,
        "execution_state": result.execution_state.value,
        "row_count": result.row_count,
        "data": result.data,
        "error": (
            {
                "code": result.error.code,
                "kind": result.error.kind.value,
                "public_message": result.error.public_message,
            }
            if result.error
            else None
        ),
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    try:
        as_of = date.fromisoformat(args.as_of)
        arguments = json.loads(args.arguments)
        if (
            args.timeout_ms < 0
            or args.max_tool_calls < 0
            or not isinstance(arguments, dict)
        ):
            raise ValueError
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError):
        return {"error": "Invalid operator arguments."}
    if args.adapter == "sqlite" and (
        not args.manufacturing_db or not args.equipment_db
    ):
        return {"error": "SQLite adapter requires both database paths."}
    if args.adapter == "sqlite":
        from ..integrations.manufacturing.sqlite_equipment_health import (
            SQLiteEquipmentHealthAdapter,
        )

        adapter = SQLiteEquipmentHealthAdapter(
            args.manufacturing_db,
            args.equipment_db,
            demo_tenant_id=args.source_tenant_id,
        )
        adapter_kind = "sqlite"
    else:
        adapter = _fake(args.source_tenant_id, as_of, arguments)
        adapter_kind = "fake"
    plan = _ready_plan(arguments, args.max_tool_calls, args.tool)
    guard = ToolLoopGuard(plan)
    context = RuntimeContext(
        _Principal(args.tenant_id, "demo-user", (args.role,)),
        "loop-demo",
        ToolExecutionLimits(
            args.max_tool_calls,
            100,
            time.monotonic() + args.timeout_ms / 1000,
        ),
    )
    model = _TwoResponseModel(args.tool, json.dumps(arguments, ensure_ascii=False))
    definition = AgentDefinition(
        "loop-health-demo",
        "1.0.0",
        "analyst",
        "Run model-selected health steps.",
        (ComponentReference("get_equipment_health", "1.0.0"),),
        ComponentReference("fixed-loop-model", "1.0.0"),
        ComponentReference("demo-equipment", "1.0.0"),
    )
    projector = ReadyResultPolicy()
    try:
        application = assemble_agent(
            definition,
            model=model,
            events=_Events([]),
            bindings=(create_equipment_health_binding(adapter, today=lambda: as_of),),
            policy=DemoToolPolicy(
                frozenset({"get_equipment_health"}),
                frozenset({"analyst"}),
                tenant_id=args.source_tenant_id,
            ),
            budget_factory=lambda: LoopGuardToolBudget(guard),
            server_capabilities=frozenset({"get_equipment_health"}),
            model_policy_ref=ComponentReference("fixed-loop-model", "1.0.0"),
            policy_ref=ComponentReference("demo-equipment", "1.0.0"),
        )
        run = application.new_run(context, result_policy=projector)
        binding = bind_loop_run(plan, guard, run, projector)
    except AssemblyError:
        return {"error": "Agent assembly is invalid."}

    progress: list[dict] = []
    emitted: list[dict] = []

    async def notify(_progress: object, event: dict) -> None:
        progress.append(
            {key: value for key, value in event.items() if key != "arguments"}
        )

    def emit_event(name: str, run_id: str, **details: object) -> None:
        emitted.append({"event": name, "run_id": run_id, **details})

    first = await run.model_stage(
        call_id="loop-model-1",
        messages=(ModelMessage("user", "Run fixed health step."),),
    )
    response = classify_loop_response(first.value)
    outcome = await execute_dispatched_loop_round(
        plan,
        guard,
        context.run_id,
        1,
        response,
        None,
        binding=binding,
        notify=notify,
        emit_event=emit_event,
    )
    tool_messages = tuple(
        ModelMessage("tool", item["content"], tool_call_id=item["tool_call_id"])
        for item in outcome.tool_messages
    )
    second = await run.model_stage(
        call_id="loop-model-2",
        messages=(
            ModelMessage("user", "Run fixed health step."),
            ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
            *tool_messages,
        ),
    )
    final_response = classify_loop_response(second.value)
    if final_response.kind != "text":
        return {"error": "Loop fixture returned an invalid final response."}
    return {
        "plan": {
            "plan_id": plan.plan_id,
            "status": plan.status,
            "steps": [
                {"step_id": step.step_id, "tool": step.tool} for step in plan.steps
            ],
        },
        "trace": outcome.trace,
        "observations": outcome.observation_payloads,
        "sources": outcome.sources,
        "typed_results": [_typed_result(result) for result in outcome.tool_results],
        "tool_messages": list(outcome.tool_messages),
        "final_response": final_response.content,
        "guard": guard.summary(),
        "model_tool_selection_calls": 1,
        "model_response_calls": len(model.requests),
        "adapter_kind": adapter_kind,
        "progress": progress,
        "events": emitted,
        "execution_mode": "model_loop",
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = asyncio.run(_run(args))
    except Exception:  # noqa: BLE001 - standalone output stays sanitized
        payload = {"error": "INTERNAL_ERROR"}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
    return (
        0
        if payload.get("typed_results", [{}])[0].get("status")
        == ToolStatus.SUCCEEDED.value
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
