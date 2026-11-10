"""Run native production report tools through the approved Ready or Loop path."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..agent_runtime.definition import AgentDefinition, ComponentReference
from ..agent_runtime.execution.loop_dispatch import execute_dispatched_loop_round
from ..agent_runtime.execution.loop_guard import ToolLoopGuard
from ..agent_runtime.execution.loop_response import classify_loop_response
from ..agent_runtime.execution.ready_dispatch import execute_dispatched_ready_plan
from ..agent_runtime.execution.ready_result_policy import ReadyResultPolicy
from ..agent_runtime.execution.runtime_contracts import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
    RuntimeContext,
    RuntimeEvent,
)
from ..agent_runtime.execution.tool_budget import LoopGuardToolBudget
from ..agent_runtime.tools.contracts import ToolExecutionLimits, ToolStatus
from ..agent_runtime.tools.dispatch_policy import DemoToolPolicy
from app.demo_data.tool_sources.production_reports import (
    FakeProductionReportsAdapter,
)
from app.tools.production_reports.data_source import (
    SQLiteProductionReportsAdapter,
)
from app.tools.production_reports.binding import (
    create_fab_overview_binding,
    create_process_pass_rate_binding,
    create_yield_trend_binding,
)
from app.tools.production_reports.contracts import (
    FabOverviewInput,
    ProcessPassRateInput,
    ProductionReportInputError,
    YieldTrendInput,
)
from ..planning_runtime.contracts import (
    AnalysisScopeContract,
    ExecutionPlan,
    PlanBudget,
    PlanStep,
)
from .agent_assembly import AssemblyError, assemble_agent
from .loop_assembly import bind_loop_run
from .ready_assembly import bind_ready_run

_TOOLS = ("get_fab_overview", "get_yield_trend", "get_process_pass_rate")


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


class _ReadyModel:
    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        raise AssertionError("Ready execution must not select tools through the model")


@dataclass(slots=True)
class _LoopModel:
    tool: str
    arguments: str
    requests: list[ModelRequest] = field(default_factory=list)

    async def complete(
        self, request: ModelRequest, context: RuntimeContext
    ) -> ModelResponse:
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall("production-tool-1", self.tool, self.arguments),
                )
            )
        if len(self.requests) == 2:
            messages = request.messages
            tool_messages = [
                item
                for item in messages
                if item.role == "tool" and item.tool_call_id == "production-tool-1"
            ]
            if len(tool_messages) != 1:
                raise AssertionError(
                    "production Loop fixture requires its tool message"
                )
            try:
                payload = json.loads(tool_messages[0].content)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise AssertionError(
                    "production Loop fixture requires JSON tool data"
                ) from exc
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("ok"), bool)
                or "data" not in payload
                or not isinstance(payload.get("execution_state"), str)
            ):
                raise AssertionError(
                    "production Loop fixture received inconsistent tool data"
                )
            return ModelResponse(
                content="Fixed production report Loop fixture completed."
            )
        raise AssertionError("unexpected production report Loop sequence")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("ready", "loop"), default="ready")
    parser.add_argument("--adapter", choices=("fake", "sqlite"), default="fake")
    parser.add_argument("--manufacturing-db")
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--source-tenant-id", default="demo")
    parser.add_argument("--role", choices=("analyst", "viewer"), default="analyst")
    parser.add_argument("--tool", default=_TOOLS[0])
    parser.add_argument("--arguments", default="{}")
    parser.add_argument("--as-of", default="2026-10-24")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--max-tool-calls", type=int, default=1)
    return parser


def _input(
    tool: str,
) -> type[FabOverviewInput | YieldTrendInput | ProcessPassRateInput] | None:
    return {
        "get_fab_overview": FabOverviewInput,
        "get_yield_trend": YieldTrendInput,
        "get_process_pass_rate": ProcessPassRateInput,
    }.get(tool)


def _fixture(
    tool: str, query: Any
) -> dict[str, object] | tuple[dict[str, object], ...]:
    """Return small, explicitly fake rows consistent with the effective query."""
    if tool == "get_fab_overview":
        return {
            "lots": 1,
            "wafers": 10,
            "good_wafers": 9,
            "yield_pct": 90.0,
            "avg_cycle_hours": 1.0,
            "avg_hold_hours": 0.0,
            "held_lots": 0,
            "excursions": 0,
            "start": query.start.isoformat(),
            "end": query.end.isoformat(),
        }
    if tool == "get_yield_trend":
        return (
            {
                "period": query.start.strftime("%Y-%W"),
                "week_start": query.start.isoformat(),
                "lots": 1,
                "yield_pct": 90.0,
                "cycle_hours": 1.0,
            },
        )
    return (
        {
            "process_step": query.process_step,
            "equipment_id": query.equipment_id,
            "runs": 1,
            "passed_runs": 1,
            "pass_pct": 100.0,
        },
    )


def _fake(
    tenant: str, as_of: date, tool: str, args: dict[str, object]
) -> FakeProductionReportsAdapter:
    model = _input(tool)
    try:
        query = model.from_arguments(args).resolve(as_of) if model else None
        return FakeProductionReportsAdapter(
            tenant, {query: _fixture(tool, query)} if query else {}
        )
    except ProductionReportInputError:
        return FakeProductionReportsAdapter(tenant, {})


def _plan(tool: str, args: dict[str, object], max_calls: int) -> ExecutionPlan:
    return ExecutionPlan(
        "production-reports-demo",
        "1",
        "demo",
        "ready",
        "",
        "",
        None,
        None,
        AnalysisScopeContract("manufacturing", (), (), ()),
        (),
        (
            PlanStep(
                "S01",
                "Production report",
                tool,
                args,
                {},
                (),
                (),
                True,
                (),
                100,
                "primary",
            ),
        ),
        PlanBudget(
            max_calls, max_calls, 2, 100, {name: max_calls for name in _TOOLS}, 1, 1
        ),
        (),
        (),
    )


def _application(
    args: argparse.Namespace,
    as_of: date,
    adapter: FakeProductionReportsAdapter | SQLiteProductionReportsAdapter,
    guard: ToolLoopGuard,
    context: RuntimeContext,
    model: _ReadyModel | _LoopModel,
):
    definition = AgentDefinition(
        "production-reports-demo",
        "1.0.0",
        "analyst",
        "Run approved production reports.",
        tuple(ComponentReference(name, "1.0.0") for name in _TOOLS),
        ComponentReference("production-reports-demo-model", "1.0.0"),
        ComponentReference("production-reports-demo-policy", "1.0.0"),
    )
    projector = ReadyResultPolicy()
    application = assemble_agent(
        definition,
        model=model,
        events=_Events([]),
        bindings=(
            create_fab_overview_binding(adapter, today=lambda: as_of),
            create_yield_trend_binding(adapter, today=lambda: as_of),
            create_process_pass_rate_binding(adapter, today=lambda: as_of),
        ),
        policy=DemoToolPolicy(
            frozenset(_TOOLS), frozenset({"analyst"}), tenant_id=args.source_tenant_id
        ),
        budget_factory=lambda: LoopGuardToolBudget(guard),
        server_capabilities=frozenset(_TOOLS),
        model_policy_ref=ComponentReference("production-reports-demo-model", "1.0.0"),
        policy_ref=ComponentReference("production-reports-demo-policy", "1.0.0"),
    )
    return application.new_run(context, result_policy=projector), projector


def _typed(result: Any) -> dict[str, object]:
    return {
        "call_id": result.call_id,
        "tool": result.tool_name,
        "version": result.tool_version,
        "status": result.status.value,
        "state": result.execution_state.value,
        "execution_state": result.execution_state.value,
        "row_count": result.row_count,
        "data": result.data,
        "error": None
        if result.error is None
        else {
            "code": result.error.code,
            "kind": result.error.kind.value,
            "public_message": result.error.public_message,
        },
    }


def _safe_plan(plan: ExecutionPlan) -> dict[str, object]:
    return {
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
            "per_tool_limits": dict(plan.budget.per_tool_limits),
        },
    }


async def _run(args: argparse.Namespace) -> dict[str, object]:
    try:
        as_of = date.fromisoformat(args.as_of)
        arguments = json.loads(args.arguments)
        if (
            not isinstance(arguments, dict)
            or args.timeout_ms < 0
            or args.max_tool_calls < 0
        ):
            raise ValueError("operator arguments are invalid")
    except (ValueError, TypeError, RecursionError, json.JSONDecodeError):
        return {"error": "Invalid operator arguments."}
    if args.adapter == "sqlite":
        if not args.manufacturing_db:
            return {"error": "SQLite adapter requires the manufacturing database."}
        adapter = SQLiteProductionReportsAdapter(
            args.manufacturing_db, demo_tenant_id=args.source_tenant_id
        )
        adapter_kind = "sqlite"
    else:
        adapter = _fake(args.source_tenant_id, as_of, args.tool, arguments)
        adapter_kind = "fake"
    plan = _plan(args.tool, arguments, args.max_tool_calls)
    guard = ToolLoopGuard(plan)
    context = RuntimeContext(
        _Principal(args.tenant_id, "demo-user", (args.role,)),
        f"production-{args.mode}-demo",
        ToolExecutionLimits(
            args.max_tool_calls, 100, time.monotonic() + args.timeout_ms / 1000
        ),
    )
    model = (
        _ReadyModel()
        if args.mode == "ready"
        else _LoopModel(args.tool, json.dumps(arguments, ensure_ascii=False))
    )
    try:
        run, projector = _application(args, as_of, adapter, guard, context, model)
        binding = (
            bind_ready_run(plan, guard, run, projector)
            if args.mode == "ready"
            else bind_loop_run(plan, guard, run, projector)
        )
    except AssemblyError:
        return {"error": "Agent assembly is invalid."}

    progress: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    async def notify(_progress: object, event: dict[str, object]) -> None:
        progress.append(
            {key: value for key, value in event.items() if key != "arguments"}
        )

    def emit_event(name: str, run_id: str, **details: object) -> None:
        events.append({"event": name, "run_id": run_id, **details})

    if args.mode == "ready":
        outcome = await execute_dispatched_ready_plan(
            plan,
            guard,
            context.run_id,
            None,
            binding=binding,
            notify=notify,
            emit_event=emit_event,
        )
        messages = []
        final = None
    else:
        first = await run.model_stage(
            call_id="production-model-1",
            messages=(ModelMessage("user", "Run fixed production report."),),
        )
        outcome = await execute_dispatched_loop_round(
            plan,
            guard,
            context.run_id,
            1,
            classify_loop_response(first.value),
            None,
            binding=binding,
            notify=notify,
            emit_event=emit_event,
        )
        messages = list(outcome.tool_messages)
        second = await run.model_stage(
            call_id="production-model-2",
            messages=(
                ModelMessage("user", "Run fixed production report."),
                ModelMessage("assistant", "", tool_calls=first.value.tool_calls),
                *(
                    ModelMessage(
                        "tool", item["content"], tool_call_id=item["tool_call_id"]
                    )
                    for item in messages
                ),
            ),
        )
        final = classify_loop_response(second.value).content
    sources = {
        source["source_ref"]: source
        for item in outcome.trace
        for source in item.get("sources", ())
    }
    return {
        "mode": args.mode,
        "adapter_kind": adapter_kind,
        "plan": _safe_plan(plan),
        "typed_results": [_typed(item) for item in outcome.tool_results],
        "trace": outcome.trace,
        "observations": outcome.observation_payloads,
        "sources": sources,
        "tool_messages": messages,
        "final_response": final,
        "guard": guard.summary(),
        "model_tool_selection_calls": 0 if args.mode == "ready" else 1,
        "model_response_calls": 0 if args.mode == "ready" else len(model.requests),
        "progress": progress,
        "events": events,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        payload = asyncio.run(_run(_parser().parse_args(argv)))
    except Exception:  # noqa: BLE001 - standalone output remains sanitized
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
