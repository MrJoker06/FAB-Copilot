"""Run one approved Ready health step through the assembled dispatcher."""

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
from ..agent_runtime.execution.ready_dispatch import execute_dispatched_ready_plan
from ..agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from ..agent_runtime.execution.runtime_contracts import (
    ModelRequest,
    ModelResponse,
    RuntimeContext,
    RuntimeEvent,
)
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.contracts import ToolExecutionLimits, ToolStatus
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from ..manufacturing.equipment_health.binding import create_equipment_health_binding
from ..planning_runtime.contracts import ExecutionPlan, PlanStep
from .agent_assembly import AssemblyError, assemble_agent
from .dispatcher_demo import _fake, _parser, _plan
from .ready_assembly import bind_ready_run


@dataclass(frozen=True, slots=True)
class _Principal:
    tenant_id: str
    user_id: str
    roles: tuple[str, ...]


@dataclass(slots=True)
class _Events:
    items: list[RuntimeEvent]

    async def emit(self, event: RuntimeEvent) -> None:
        self.items.append(event)


class _NeverSelectModel:
    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        raise AssertionError("Ready execution must not select tools through the model")


def _ready_plan(
    arguments: dict[str, object], max_calls: int, tool_name: str
) -> ExecutionPlan:
    base = _plan(max_calls)
    step = PlanStep(
        "health",
        "Equipment health",
        tool_name,
        arguments,
        {},
        (),
        (),
        True,
        (),
        100,
        "primary",
    )
    return ExecutionPlan(
        base.plan_id,
        base.schema_version,
        base.planner_version,
        base.status,
        base.reason,
        base.route_intent,
        base.playbook_id,
        base.playbook_version,
        base.scope_contract,
        base.required_evidence_ids,
        (step,),
        base.budget,
        base.missing_inputs,
        base.clarification_questions,
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
        arguments = json.loads(args.arguments)
        if not isinstance(arguments, dict):
            raise TypeError
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
    deadline = time.monotonic() + args.timeout_ms / 1000
    context = RuntimeContext(
        _Principal(args.tenant_id, "demo-user", (args.role,)),
        "ready-demo",
        ToolExecutionLimits(args.max_tool_calls, 100, deadline),
    )
    definition = AgentDefinition(
        "ready-health-demo",
        "1.0.0",
        "analyst",
        "Run approved health steps.",
        (ComponentReference("get_equipment_health", "1.0.0"),),
        ComponentReference("never-select", "1.0.0"),
        ComponentReference("demo-equipment", "1.0.0"),
    )
    projector = ReadyResultPolicy()
    events = _Events([])
    try:
        application = assemble_agent(
            definition,
            model=_NeverSelectModel(),
            events=events,
            bindings=(create_equipment_health_binding(adapter, today=lambda: as_of),),
            policy=DemoToolPolicy(
                frozenset({"get_equipment_health"}),
                frozenset({"analyst"}),
                tenant_id=args.source_tenant_id,
            ),
            budget_factory=lambda: LoopGuardToolBudget(guard),
            server_capabilities=frozenset({"get_equipment_health"}),
            model_policy_ref=ComponentReference("never-select", "1.0.0"),
            policy_ref=ComponentReference("demo-equipment", "1.0.0"),
        )
        run = application.new_run(context, result_policy=projector)
        binding = bind_ready_run(plan, guard, run, projector)
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

    outcome = await execute_dispatched_ready_plan(
        plan,
        guard,
        context.run_id,
        None,
        binding=binding,
        notify=notify,
        emit_event=emit_event,
    )
    return {
        "plan": {
            "plan_id": plan.plan_id,
            "status": plan.status,
            "steps": [
                {
                    "step_id": step.step_id,
                    "tool": step.tool,
                    "depends_on": list(step.depends_on),
                }
                for step in plan.steps
            ],
            "budget": {
                "max_tool_calls": plan.budget.max_tool_calls,
                "max_rows_per_call": plan.budget.max_rows_per_call,
            },
        },
        "trace": outcome.trace,
        "observations": outcome.observation_payloads,
        "sources": outcome.sources,
        "typed_results": [
            {
                "call_id": result.call_id,
                "tool": result.tool_name,
                "version": result.tool_version,
                "status": result.status.value,
                "state": result.execution_state.value,
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
            for result in outcome.tool_results
        ],
        "guard": guard.summary(),
        "model_tool_selection_calls": 0,
        "adapter_kind": adapter_kind,
        "progress": progress,
        "events": emitted,
    }


def main(argv: list[str] | None = None) -> int:
    args = _agent_parser().parse_args(argv)
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
