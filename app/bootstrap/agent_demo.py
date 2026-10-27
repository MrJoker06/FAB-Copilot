"""Explicit agent-assembly demonstration with a fake model and read-only tool."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..agent_runtime.definition import AgentDefinition, ComponentReference
from ..agent_runtime.execution.loop_guard import ToolLoopGuard
from ..agent_runtime.execution.runtime_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
    RuntimeEvent,
)
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.execution.tool_result_bridge import project_tool_result
from ..agent_runtime.tools.contracts import ToolExecutionLimits, ToolStatus
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from ..manufacturing.equipment_health.binding import create_equipment_health_binding
from .agent_assembly import AssemblyError, assemble_agent
from .dispatcher_demo import _fake, _parser, _plan


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]


@dataclass(slots=True)
class _FakeEvents:
    items: list[RuntimeEvent]

    async def emit(self, event: RuntimeEvent) -> None:
        self.items.append(event)


@dataclass(frozen=True, slots=True)
class _FakeModel:
    tool: str
    arguments: str

    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        return ModelResponse(
            tool_calls=(ModelToolCall("model-picked", self.tool, self.arguments),)
        )


def _agent_parser() -> argparse.ArgumentParser:
    parser = _parser()
    parser.description = __doc__
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        as_of = date.fromisoformat(args.as_of)
        if args.timeout_ms < 0 or args.max_tool_calls < 0:
            raise ValueError
    except (TypeError, ValueError):
        return {"error": "Invalid operator arguments."}
    try:
        arguments = json.loads(args.arguments)
    except (TypeError, ValueError, RecursionError):
        arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
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
        source_kind = "sqlite"
    else:
        adapter = _fake(args.source_tenant_id, as_of, arguments)
        source_kind = "fake"
    binding = create_equipment_health_binding(adapter, today=lambda: as_of)
    definition = AgentDefinition(
        "equipment-health-demo",
        "1.0.0",
        "analyst",
        "Use the declared health tool only when authorized.",
        (ComponentReference("get_equipment_health", "1.0.0"),),
        ComponentReference("fake-model", "1.0.0"),
        ComponentReference("demo-equipment", "1.0.0"),
    )
    events = _FakeEvents([])
    deadline = time.monotonic() + args.timeout_ms / 1000
    context = RuntimeContext(
        _Principal(args.tenant_id, "demo-user", (args.role,)),
        "agent-assembly-demo",
        ToolExecutionLimits(args.max_tool_calls, 100, deadline),
    )
    guard: ToolLoopGuard | None = None

    def budget_factory() -> LoopGuardToolBudget:
        nonlocal guard
        guard = ToolLoopGuard(_plan(args.max_tool_calls))
        return LoopGuardToolBudget(guard)

    try:
        application = assemble_agent(
            definition,
            model=_FakeModel(args.tool, args.arguments),
            events=events,
            bindings=(binding,),
            policy=DemoToolPolicy(
                frozenset({"get_equipment_health"}),
                frozenset({"analyst"}),
                tenant_id=args.source_tenant_id,
            ),
            budget_factory=budget_factory,
            server_capabilities=frozenset({"get_equipment_health"}),
            model_policy_ref=ComponentReference("fake-model", "1.0.0"),
            policy_ref=ComponentReference("demo-equipment", "1.0.0"),
        )
        run = application.new_run(context)
        model_stage = await run.model_stage(
            call_id="model-stage", messages=(ModelMessage("user", "health check"),)
        )
        await run.publish(model_stage.event)
        call = model_stage.value.tool_calls[0]
        tool_stage = await run.tool_stage(call, call_id="tool-stage", step_id="health")
        await run.publish(tool_stage.event)
    except AssemblyError:
        return {"error": "Agent assembly is invalid."}
    projection = project_tool_result(
        tool_stage.value, arguments=arguments, step_id="health"
    )
    result = tool_stage.value
    return {
        "definition": {
            "agent_id": definition.agent_id,
            "version": definition.version,
            "tool_refs": [
                {"component_id": item.component_id, "version": item.version}
                for item in definition.tools
            ],
            "model_policy": {
                "component_id": definition.model_policy.component_id,
                "version": definition.model_policy.version,
            },
            "default_policy": {
                "component_id": definition.default_policy.component_id,
                "version": definition.default_policy.version,
            },
        },
        "effective_capabilities": sorted(application.effective_capabilities),
        "model": "fake",
        "source_kind": source_kind,
        "result": {
            "call_id": result.call_id,
            "tool": result.tool_name,
            "version": result.tool_version,
            "status": result.status.value,
            "execution_state": result.execution_state.value,
            "row_count": result.row_count,
            "elapsed_ms": result.elapsed_ms,
            "error": (
                {
                    "code": result.error.code,
                    "kind": result.error.kind.value,
                    "public_message": result.error.public_message,
                }
                if result.error
                else None
            ),
            "data": result.data,
            "sources": list(projection.sources),
            "observation": projection.observation,
        },
        "summary_events": [
            {
                "run_id": event.run_id,
                "call_id": event.call_id,
                "kind": event.kind,
                "status": event.status.value,
                "schema_version": event.schema_version,
                "execution_state": (
                    event.execution_state.value if event.execution_state else None
                ),
            }
            for event in events.items
        ],
        "trace": projection.trace,
        "guard": guard.summary() if guard is not None else {},
    }


def main(argv: list[str] | None = None) -> int:
    args = _agent_parser().parse_args(argv)
    try:
        payload = asyncio.run(_run(args))
    except Exception:  # noqa: BLE001 - operator output must remain sanitized
        payload = {"error": "INTERNAL_ERROR"}
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
    return (
        0
        if payload.get("result", {}).get("status") == ToolStatus.SUCCEEDED.value
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
